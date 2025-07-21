Tool Enabled Installation
=========================

This tutorial guides you through setting up the vLLM Production Stack with tool calling support using the Llama-3.1-8B-Instruct model. This setup enables your model to interact with external tools and functions through a structured interface.

Prerequisites
-------------

1. All prerequisites from the :doc:`../getting_started/quickstart` tutorial
2. A Hugging Face account with access to Llama-3.1-8B-Instruct
3. Accepted terms for meta-llama/Llama-3.1-8B-Instruct on Hugging Face
4. A valid Hugging Face token
5. Python 3.7+ installed on your local machine
6. The ``openai`` Python package installed (``pip install openai``)
7. Access to a Kubernetes cluster with storage provisioner support

Steps
-----

1. Set up vLLM Templates and Storage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

First, run the setup script to download templates and create the necessary Kubernetes resources:

.. code-block:: bash

   # Make the script executable
   chmod +x scripts/setup_vllm_templates.sh

   # Run the setup script
   ./scripts/setup_vllm_templates.sh

This script will:

1. Download the required templates from the vLLM repository
2. Create a PersistentVolume for storing the templates
3. Create a PersistentVolumeClaim for accessing the templates
4. Verify the setup is complete

The script uses consistent naming that matches the deployment configuration:

- PersistentVolume: ``vllm-templates-pv``
- PersistentVolumeClaim: ``vllm-templates-pvc``

2. Set up Hugging Face Credentials
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create a Kubernetes secret with your Hugging Face token:

.. code-block:: bash

   kubectl create secret generic huggingface-credentials \
     --from-literal=HUGGING_FACE_HUB_TOKEN=your_token_here

3. Deploy vLLM Instance with Tool Calling Support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

3.1: Use the Example Configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

We'll use the example configuration file located at ``tutorials/assets/values-08-tool-enabled.yaml``. This file contains all the necessary settings for enabling tool calling:

.. code-block:: yaml

   servingEngineSpec:
     runtimeClassName: ""
     modelSpec:
     - name: "llama3-8b"
       repository: "vllm/vllm-openai"
       tag: "latest"
       modelURL: "meta-llama/Llama-3.1-8B-Instruct"

       # Tool calling configuration
       enableTool: true
       toolCallParser: "llama3_json"  # Parser to use for tool calls (e.g., "llama3_json" for Llama models)
       chatTemplate: "tool_chat_template_llama3.1_json.jinja"  # Template file name (will be mounted at /vllm/templates)

       # Mount Hugging Face credentials
       env:
         - name: HUGGING_FACE_HUB_TOKEN
           valueFrom:
             secretKeyRef:
               name: huggingface-credentials
               key: HUGGING_FACE_HUB_TOKEN

       replicaCount: 1

       # Resource requirements for Llama-3.1-8B-Instruct
       requestCPU: 8
       requestMemory: "32Gi"
       requestGPU: 1

.. note::
   The tool calling configuration is now simplified:

   - ``enableTool: true`` enables the feature
   - ``toolCallParser``: specifies how the model's tool calls are parsed (using "llama3_json" for Llama-3 models)
   - ``chatTemplate``: specifies the template file name (will be mounted at ``/vllm/templates/``)

   The chat templates are managed through a PersistentVolume that we created in step 1, which provides several benefits:

   - Templates are downloaded once and stored persistently
   - Templates can be shared across multiple deployments
   - Templates can be updated by updating the files in the PersistentVolume
   - Templates are version controlled with the vLLM repository

3.2: Deploy the Helm Chart
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   # Add the vLLM Helm repository if you haven't already
   helm repo add vllm https://vllm-project.github.io/production-stack

   # Deploy the vLLM stack with tool calling support using the example configuration
   helm install vllm-tool vllm/vllm-stack -f tutorials/assets/values-08-tool-enabled.yaml

The deployment will:

1. Use the PersistentVolume we created in step 1 to access the templates
2. Mount the templates at ``/vllm/templates`` in the container
3. Configure the model to use the specified template for tool calling

You can verify the deployment with:

.. code-block:: bash

   # Check the deployment status
   kubectl get deployments

   # Check the pods
   kubectl get pods

   # Check the logs
   kubectl logs -f deployment/vllm-tool-llama3-8b-deployment-vllm

4. Test Tool Calling Setup
~~~~~~~~~~~~~~~~~~~~~~~~~~

Now that the deployment is running, let's test the tool calling functionality using the example script.

4.1: Port Forward the Router Service
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

First, we need to set up port forwarding to access the router service:

.. code-block:: bash

   # Get the service name
   kubectl get svc

   # Set up port forwarding to the router service
   kubectl port-forward svc/vllm-tool-router-service 8000:80

4.2: Run the Example Script
^^^^^^^^^^^^^^^^^^^^^^^^^^^

In a new terminal, run the example script to test tool calling:

.. code-block:: bash

   # Navigate to the examples directory
   cd src/examples

   # Run the example script
   python tool_calling_example.py

The script will:

1. Connect to the vLLM service through the port-forwarded endpoint
2. Send a test query asking about the weather
3. Demonstrate the model's ability to:

   - Understand the available tools
   - Make appropriate tool calls
   - Process the tool responses

Expected output should look something like:

.. code-block:: text

   Function called: get_weather
   Arguments: {"location": "San Francisco, CA", "unit": "celsius"}
   Result: Getting the weather for San Francisco, CA in celsius...

This confirms that:

1. The vLLM service is running correctly
2. Tool calling is properly enabled
3. The model can understand and use the defined tools
4. The template system is working as expected

.. note::
   The example uses a mock weather function for demonstration. In a real application, you would replace this with actual API calls to weather services.
