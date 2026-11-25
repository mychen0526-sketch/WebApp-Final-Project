#!/bin/sh
# Lambda handler: Lambda Web Adapter (layer, via AWS_LAMBDA_EXEC_WRAPPER=/opt/bootstrap) starts this
# script and forwards Function URL requests and async/EventBridge events to uvicorn on :8000.
exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
