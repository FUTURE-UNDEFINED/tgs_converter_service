import abc
import asyncio
import gzip
import io
import json
import ffmpeg
import grpc

from PIL import Image

from generated.telegram_stickers_converter.telegram_stickers_converter_pb2 import OutputFormat, GetStickerRequest, \
    StickerFileMetadata, StickerFileChunk
from generated.telegram_stickers_converter import telegram_stickers_converter_pb2_grpc
from tgs_converter.bot import bot
from rlottie_python import LottieAnimation


class StickerProcessor(abc.ABC):
    @abc.abstractmethod
    async def process(self, data: bytes, in_format: str, out_format: str, width: int, height: int) -> bytes:
        pass


class AnimatedStickersProcessor(StickerProcessor):
    __allowed_output_formats = ['png', 'jpg', 'webp', 'webm', 'mp4', 'gif']
    __animated = ['webm', 'mp4', 'gif']
    __static = ['png', 'jpg', 'webp']

    async def process(self, data: bytes, in_format: str, out_format: str, width: int, height: int) -> bytes:
        if in_format != 'tgs':
            raise ValueError('Only TGS format is supported for animated stickers')
        if out_format not in self.__allowed_output_formats:
            raise ValueError(f'Unsupported output format: {out_format}')
        unzipped = gzip.decompress(data)
        lottie_json = json.loads(unzipped.decode('utf-8'))
        animation = LottieAnimation.from_data(json.dumps(lottie_json))

        if out_format in self.__animated:
            total_frames = animation.lottie_animation_get_totalframe()
            try:
                ENCODE_PRESETS = {
                    "mp4": {
                        "vcodec": "libx264",
                        "format": "mp4",
                        "pix_fmt": "yuv420p",
                        "extra_args": {
                            "movflags": "frag_keyframe+empty_moov",
                            "preset": "ultrafast",
                            "tune": "zerolatency",
                        },
                    },
                    "webm": {
                        "vcodec": "libvpx",
                        "format": "webm",
                        "pix_fmt": "yuv420p",
                        "extra_args": {
                            "b:v": "0",
                            "deadline": "realtime",
                            "cpu-used": "5",
                            "crf": "32"
                        },
                    },
                    "gif": {
                        "vcodec": None,
                        "format": "gif",
                        "pix_fmt": "rgb24",
                        "extra_args": {},
                    },
                }

                preset = ENCODE_PRESETS[out_format]
                process = (
                    ffmpeg
                    .input(
                        "pipe:0",
                        format="rawvideo",
                        pix_fmt="bgra",
                        s=f"{width}x{height}",
                        framerate=animation.lottie_animation_get_framerate()
                    )
                    .output(
                        "pipe:1",
                        format=preset["format"],
                        vcodec=preset["vcodec"],
                        pix_fmt=preset["pix_fmt"],
                        vframes=total_frames,
                        **preset["extra_args"],
                        shortest=None
                    )
                    .global_args("-loglevel", "error")
                    .run_async(pipe_stdin=True, pipe_stdout=True, pipe_stderr=True)
                )

                for i in range(total_frames):
                    print("1111")

                    frame_bytes = animation.lottie_animation_render(
                        frame_num=i, width=width, height=height
                    )
                    if len(frame_bytes) != width * height * 4:
                        raise ConvertationError("Frame size mismatch")
                    process.stdin.write(frame_bytes)

                process.stdin.close()
                out_data, err = await asyncio.get_running_loop().run_in_executor(
                    None, process.communicate
                )

                if process.returncode != 0:
                    raise ConvertationError(f'ffmpeg failed: {err.decode("utf-8")}')
                return out_data
            except Exception as e:
                raise ConvertationError(f'ffmpeg failed: {e}')

        if out_format in self.__static:
            buffer = animation.lottie_animation_render(0, width=width, height=height)
            image = Image.frombuffer('RGBA', (width, height), buffer, 'raw', 'BGRA')
            output = io.BytesIO()
            image.save(output, format=out_format.upper())

            return output.getvalue()

        raise ConvertationError("Unsupported output format")


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

            loop = asyncio.get_running_loop()
            input_bytes = input_stream.read()
            out_data, err = await loop.run_in_executor(
                None, lambda: process.communicate(input=input_bytes)
            )
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


CONTENT_TYPES = {
    "webp": "image/webp",
    "png": "image/png",
    "jpg": "image/jpeg",
    "mp4": "video/mp4",
    "webm": "video/webm",
    "gif": "image/gif"
}

OUTPUT_FORMAT_PROTO_MAP = {
    "png": OutputFormat.OUTPUT_FORMAT_PNG,
    "webp": OutputFormat.OUTPUT_FORMAT_WEBP_STATIC,
    "jpg": OutputFormat.OUTPUT_FORMAT_JPG,
    "mp4": OutputFormat.OUTPUT_FORMAT_MP4,
    "webm": OutputFormat.OUTPUT_FORMAT_WEBM,
    "gif": OutputFormat.OUTPUT_FORMAT_GIF,
}

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
        OutputFormat.OUTPUT_FORMAT_JPG: "jpg",
        OutputFormat.OUTPUT_FORMAT_MP4: "mp4"
    }
    return x[output_format]


class TelegramStickersConverterServicer(telegram_stickers_converter_pb2_grpc.StickerConverterServiceServicer):
    async def GetSticker(self, request: GetStickerRequest, context: grpc.aio.ServicerContext):
        print("incoming ;)")
        try:
            file_info = await self.__get_file_info(request.sticker_file_id, context)
            byte_array = await file_info.download_as_bytearray()
            file_bytes = bytes(byte_array)
        except (GetFileError, FileDownloadError) as e:
            print(f"Error fetching file: {e}")
            return

        try:
            processor = (
                asp if request.is_animated else
                vsp if request.is_video else
                ssp
            )
            in_format = infer_sticker_type(request, file_bytes)
            out_format = output_format_to_str(request.desired_format)

            async for chunk in self.__run_process_and_stream(processor, file_bytes, in_format, out_format,
                                                             request.width, request.height,
                                                             request.sticker_file_id):
                yield chunk

        except Exception as e:
            print(f"Processing error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Processing error: {str(e)}")
            return

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

    async def __run_process_and_stream(self, processor: StickerProcessor, file_bytes: bytes,
                                       in_format: str, out_format: str,
                                       width: int, height: int,
                                       sticker_file_id: str):
        result = await processor.process(file_bytes, in_format, out_format, width, height)

        chunk_size = 2 ** 18
        chunks_count = (len(result) + chunk_size - 1) // chunk_size

        content_type = CONTENT_TYPES[out_format]
        proto_format = OUTPUT_FORMAT_PROTO_MAP[out_format]

        meta = StickerFileMetadata(
            input_file_id=sticker_file_id,
            content_type=content_type,
            actual_format=proto_format
        )
        yield StickerFileChunk(metadata=meta)

        for i in range(chunks_count):
            start = i * chunk_size
            end = start + chunk_size
            chunk = result[start:end]
            yield StickerFileChunk(data_chunk=chunk)


    def __build_grpc_chunks(self, result: bytes, sticker_file_id: str):
        chunk_size = 2 ** 18
        chunks_count = (len(result) + chunk_size - 1) // chunk_size

        meta = StickerFileMetadata(
            input_file_id=sticker_file_id,
            content_type="image/png",
            actual_format=OutputFormat.OUTPUT_FORMAT_WEBM
        )
        yield StickerFileChunk(metadata=meta)

        for i in range(chunks_count):
            start = i * chunk_size
            end = start + chunk_size
            chunk = result[start:end]
            yield StickerFileChunk(data_chunk=chunk)
