#!/usr/bin/env bash
python3.6 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. service/service_spec/semantic_segmentation_aerial.proto