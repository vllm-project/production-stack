Docker Guide
============

This section provides information about Docker containerization and custom image development for the vLLM Production Stack.

Build Docker Image
------------------

Run this command from the root folder path of the project:

.. code-block:: bash

   docker build -t <image_name>:<tag> -f docker/Dockerfile .
