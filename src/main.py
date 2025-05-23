import sys
import os

current_script_dir = os.path.dirname(os.path.abspath(__file__))
generated_dir_path = os.path.join(current_script_dir, "generated")
if generated_dir_path not in sys.path:
    sys.path.insert(0, generated_dir_path)

import asyncio
import grpc.aio

from src.server import TelegramStickersConverterServicer
from v1.telegram_stickers_converter.telegram_stickers_converter_pb2_grpc import \
    add_StickerConverterServiceServicer_to_server


async def serve():
    print("Async gRPC server starting...")
    server = grpc.aio.server()
    add_StickerConverterServiceServicer_to_server(
        TelegramStickersConverterServicer(), server
    )
    server.add_insecure_port("[::]:5051")
    await server.start()
    print("Server started.")
    await server.wait_for_termination()


if __name__ == '__main__':
    asyncio.run(serve())
