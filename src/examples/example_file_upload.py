import argparse

import aiohttp


async def upload_file(server_url: str, file_path: str):
    """Uploads a file to the production stack."""
    try:
        with open(file_path, "rb") as file:
            files = {"file": (file_path, file, "application/octet-stream")}
            data = {"purpose": "unknown"}

            async with aiohttp.ClientSession() as client:
                async with client.post(server_url, files=files, data=data) as response:
                    if response.status == 200:
                        result = await response.json()
                        print("File uploaded successfully:", result)
                    else:
                        text = await response.text()
                        print("Failed to upload file:", text)
    except Exception as e:
        print(f"Error: {e}")


def parse_args():
    """Parses command line arguments."""
    parser = argparse.ArgumentParser(description="Uploads a file to the stack.")
    parser.add_argument("--path", type=str, help="Path to the file to upload.")
    parser.add_argument("--url", type=str, help="URL of the stack (router service).")

    return parser.parse_args()


if __name__ == "__main__":
    import asyncio

    args = parse_args()
    endpoint = args.url
    file_to_upload = args.path
    asyncio.run(upload_file(endpoint, file_to_upload))
