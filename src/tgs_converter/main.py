import sys
import os
from os import environ

current_script_dir = os.path.dirname(os.path.abspath(__file__))
generated_dir_path = os.path.join(current_script_dir, "generated")
if generated_dir_path not in sys.path:
    sys.path.insert(0, generated_dir_path)

import asyncio
import grpc.aio

from tgs_converter.server import TelegramStickersConverterServicer
from generated.telegram_stickers_converter.telegram_stickers_converter_pb2_grpc import add_StickerConverterServiceServicer_to_server


async def serve():
    print("Async gRPC server starting...")
    server = grpc.aio.server()
    add_StickerConverterServiceServicer_to_server(
        TelegramStickersConverterServicer(), server
    )
    grpc_port = environ.get("GRPC_PORT", "50051")

    actual_port = server.add_insecure_port(f"[::]:{grpc_port}")
    await server.start()
    print(f"Server started at port {actual_port}.")
    await server.wait_for_termination()

def main():
    asyncio.run(serve())