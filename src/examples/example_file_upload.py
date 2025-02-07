import argparse

import httpx
import requests


def upload_file(server_url: str, file_path: str):
    """Uploads a file to the production stack."""
    try:
        with open(file_path, "rb") as file:
            files = {"file": (file_path, file, "application/octet-stream")}
            data = {"purpose": "unknown"}

            with httpx.Client() as client:
                response = client.post(server_url, files=files, data=data)

                if response.status_code == 200:
                    print("File uploaded successfully:", response.json())
                else:
                    print("Failed to upload file:", response.text)
    except Exception as e:
        print(f"Error: {e}")


def parse_args():
    """Parses command line arguments."""
    parser = argparse.ArgumentParser(description="Uploads a file to the stack.")
    parser.add_argument("--path", type=str, help="Path to the file to upload.")
    parser.add_argument("--url", type=str, help="URL of the stack (router service).")

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    endpoint = args.url
    file_to_upload = args.path
    upload_file(endpoint, file_to_upload)
