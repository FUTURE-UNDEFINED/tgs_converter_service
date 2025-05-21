import abc
import gzip
import io
import json

import aiohttp
import ffmpeg
import grpc
from typing import List

from PIL import Image

from v1.telegram_stickers_converter.telegram_stickers_converter_pb2 import OutputFormat, GetStickerRequest, \
    StickerFileMetadata, StickerFileChunk
from v1.telegram_stickers_converter import telegram_stickers_converter_pb2_grpc
from bot import bot
from rlottie_python import LottieAnimation


class StickerProcessor(abc.ABC):
    @abc.abstractmethod
    async def process(self, data: bytes, in_format: str, out_format: str, width: int, height: int) -> bytes:
        pass


class AnimatedStickersProcessor(StickerProcessor):
    __allowed_output_formats = ['png', 'jpg', 'webp', 'webm', 'mp4', 'gif']

    async def process(self, data: bytes, in_format: str, out_format: str, width: int, height: int) -> bytes:
        if in_format != 'tgs':
            raise ValueError('Only TGS format is supported for animated stickers')
        if out_format not in self.__allowed_output_formats:
            raise ValueError(f'Unsupported output format: {out_format}')

        unzipped = gzip.decompress(data)
        lottie_json = json.loads(unzipped.decode('utf-8'))

        animation = LottieAnimation.from_data(json.dumps(lottie_json))
        surface = animation.lottie_animation_render(0)

        image = Image.frombytes('RGBA', (width, height), surface)
        output = io.BytesIO()

        image.save(output, format=out_format.upper())

        return output.getvalue()


class StaticStickerProcessor(StickerProcessor):
    __allowed_output_formats = ['png', 'jpg', 'webp']

    async def process(self, data: bytes, in_format: str, out_format: str, width: int, height: int) -> bytes:
        if in_format not in ('png', 'webp'):
            raise ValueError(f'Unsupported static format: {in_format}')
        if out_format not in self.__allowed_output_formats:
            raise ValueError(f'Unsupported output format: {out_format}')

        image = Image.open(io.BytesIO(data)).convert('RGBA')
        if width and height:
            image = image.resize((width, height))

        output = io.BytesIO()
        image.save(output, format=out_format.upper())
        return output.getvalue()



class VideoStickerProcessor(StickerProcessor):
    __allowed_output_formats = ['mp4', 'mpeg', 'gif', 'webm', 'mov', 'webp']

    async def process(self, data: bytes, in_format: str, out_format: str, width: int, height: int) -> bytes:
        if in_format != 'webm':
            raise ValueError('Only webm is supported as input format for video stickers')
        if out_format not in self.__allowed_output_formats:
            raise ValueError(f'Unsupported output format: {out_format}')

        input_stream = io.BytesIO(data)
        output = io.BytesIO()

        try:
            process = (
                ffmpeg
                .input('pipe:0')
                .output('pipe:1', format=out_format, vf=f'scale={width}:{height}')
                .global_args('-loglevel', 'error')
                .run_async(pipe_stdin=True, pipe_stdout=True, pipe_stderr=True)
            )

            out_data, err = process.communicate(input=input_stream.read())

            if process.returncode != 0:
                raise ConvertationError(f'ffmpeg failed: {err.decode("utf-8")}')
            return out_data
        except Exception as e:
            raise ConvertationError(f'Video conversion failed: {e}')




asp = AnimatedStickersProcessor()
ssp = StaticStickerProcessor()
vsp = VideoStickerProcessor()


def infer_sticker_type(request: GetStickerRequest, data: bytes) -> str:
    if request.is_animated:
        return 'tgs'
    if request.is_video:
        return 'webm'
    if data.startswith(bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])):
        return 'png'
    if data.startswith(b"RIFF") and b"WEBP" in data[8:12]:
        return 'webp'
    raise ValueError('Unsupported sticker type')


class FileDownloadError(Exception):
    """Custom exception to indicate failure during file download."""
    pass


class GetFileError(Exception):
    """Custom exception to indicate failure during file download."""
    pass


class ConvertationError(Exception):
    """Custom exception to indicate failure during file convertation."""
    pass


def output_format_to_str(output_format: OutputFormat) -> str:
    x = {
        OutputFormat.OUTPUT_FORMAT_PNG: 'png',
        OutputFormat.OUTPUT_FORMAT_WEBP_STATIC: 'webp',
        OutputFormat.OUTPUT_FORMAT_WEBP_ANIMATED: 'webp',
        OutputFormat.OUTPUT_FORMAT_GIF: 'gif',
        OutputFormat.OUTPUT_FORMAT_WEBM: 'webm',
        OutputFormat.OUTPUT_FORMAT_SVG: 'svg',
        OutputFormat.OUTPUT_FORMAT_TGS_RAW: 'tgs',
        OutputFormat.OUTPUT_FORMAT_PNG_SEQUENCE: 'png',
    }
    return x[output_format]


class TelegramStickersConverterServicer(telegram_stickers_converter_pb2_grpc.StickerConverterServiceServicer):
    async def __get_file_bytes(self, file_path: str, context: grpc.ServicerContext) -> bytes:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(file_path) as response:
                    response.raise_for_status()
                    file_bytes = await response.read()
                    if not file_bytes:
                        raise FileDownloadError("Downloaded file is empty.")
        except aiohttp.ClientError as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Error downloading file: {e}")
            raise FileDownloadError(f"Network error while downloading file: {e}")
        except Exception as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Unexpected error: {e}")
            raise FileDownloadError(f"Unexpected error while downloading file: {e}")

        return file_bytes

    async def __get_file_info(self, file_id: str, context: grpc.ServicerContext):
        try:
            file_info = await bot.get_file(file_id=file_id)
        except Exception as e:
            print(f"Error getting file info from Telegram: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Error getting file info: {e}")
            raise GetFileError

        if not file_info.file_path:
            print("File path not found in file_info")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details("File path not available from Telegram.")
            raise GetFileError

        return file_info

    async def GetSticker(self, request: GetStickerRequest,
                         context: grpc.ServicerContext):
        try:
            file_info = await self.__get_file_info(request.sticker_file_id, context)
        except GetFileError as e:
            print(f"Error getting file info from Telegram: {e}")
            return

        try:
            byte_array = await file_info.download_as_bytearray()
            file_bytes = bytes(byte_array)
        except FileDownloadError as e:
            print(f"Error downloading file: {e}")
            return

        processor: StickerProcessor
        if request.is_animated:
            processor = asp
        elif request.is_video:
            processor = vsp
        else:
            processor = ssp

        in_format = infer_sticker_type(request, file_bytes)
        out_format = output_format_to_str(request.desired_format)

        try:
            result_bytes = await processor.process(file_bytes, in_format, out_format, 1024, 1024)
        except ConvertationError as e:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Error converting file: {e}")
            return

        chunk_size = 2048
        chunks_count = (len(result_bytes) + chunk_size - 1) // chunk_size

        meta = StickerFileMetadata(
            input_file_id=request.sticker_file_id,
            content_type="image/png",
            actual_format=OutputFormat.OUTPUT_FORMAT_WEBM
        )
        yield StickerFileChunk(metadata=meta)

        for i in range(chunks_count):
            start = i * chunk_size
            end = start + chunk_size
            chunk = result_bytes[start:end]
            yield StickerFileChunk(data_chunk=chunk)
