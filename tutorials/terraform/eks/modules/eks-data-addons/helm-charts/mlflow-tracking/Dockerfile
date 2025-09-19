# This Dockerfile is used for MLFlow Tracking addon
# docker buildx build --platform=linux/amd64 -t mlflow:latest .
# This docker image is available at public.ecr.aws/data-on-eks/mlflow


FROM python:3.12-slim

# Build dependencies
RUN apt-get update -y && \
  apt-get install -y --no-install-recommends build-essential libpq-dev

#

RUN python -m pip install --upgrade pip && \
  pip install --no-cache-dir mlflow[extras]==2.11.1 boto3 psycopg2-binary PyMySQL

EXPOSE 5000

ENTRYPOINT ["mlflow"]
