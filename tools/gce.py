#!/usr/bin/env python3

"""
CLI script to manually create and delete runner instances on Google Cloud Platform.
This script uses the GCloudClient to interact with the GCE API.
It is intended for testing purposes to verify instance creation and deletion logic
without triggering the full webhook flow.
"""

import argparse
import logging
import sys
import os
import importlib.util

# Load the gcloud_client module directly without importing the app package
# This avoids triggering app/__init__.py which imports Flask
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
gcloud_client_path = os.path.join(parent_dir, 'app', 'clients', 'gcloud_client.py')

spec = importlib.util.spec_from_file_location("gcloud_client", gcloud_client_path)
gcloud_client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gcloud_client)

GCloudClient = gcloud_client.GCloudClient

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def main():
    parser = argparse.ArgumentParser(description="CLI for GCloudClient to create/delete runner instances.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Create command
    create_parser = subparsers.add_parser("create", help="Create a runner instance")
    create_parser.add_argument("--token", required=True, help="Registration token")
    create_parser.add_argument("--url", required=True, help="Repository URL")
    create_parser.add_argument("--template", required=True, help="Instance template name")

    # Delete command
    delete_parser = subparsers.add_parser("delete", help="Delete a runner instance")
    delete_parser.add_argument("--instance", required=True, help="Instance name")

    args = parser.parse_args()

    # Initialize client
    # Note: This relies on environment variables GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_ZONE being set,
    # or defaults in the client.
    try:
        client = GCloudClient()
    except Exception as e:
        print(f"Failed to initialize GCloudClient: {e}")
        sys.exit(1)

    if args.command == "create":
        try:
            instance_name = client.create_runner_instance(args.token, args.url, args.template)
            if instance_name:
                print(f"Successfully started creation of instance: {instance_name}")
            else:
                print("Failed to start instance creation (check logs).")
                sys.exit(1)
        except Exception as e:
            print(f"Error creating instance: {e}")
            sys.exit(1)

    elif args.command == "delete":
        try:
            client.delete_runner_instance(args.instance)
            print(f"Successfully started deletion of instance: {args.instance}")
        except Exception as e:
            print(f"Error deleting instance: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
