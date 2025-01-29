#!/bin/bash

# Loop through ports 30080 to 30090
for port in {30080..30090}
do
  # Find the process ID (PID) using the port
  PID=$(sudo netstat -tulnp | grep ":$port" | awk '{print $7}' | cut -d'/' -f1 | head -n 1)

  if [ -n "$PID" ]; then
    echo "Killing process with PID: $PID using port $port"
    sudo kill -9 "$PID"
  else
    echo "No process found using port $port"
  fi
done
