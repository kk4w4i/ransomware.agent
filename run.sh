#!/bin/bash

set -e

# Remove all containers using the ransomware-agent image
containers=$(docker ps -a -q --filter ancestor=ransomware-agent)
if [ -n "$containers" ]; then
  echo "Removing old containers..."
  docker rm -f $containers
fi

# Build the image
echo "Building Docker image..."
docker build -t ransomware-agent .
if [ $? -ne 0 ]; then
  echo "Docker build failed!"
  exit 1
fi

# Run the container interactively with host network
echo "Running the container..."
docker run --rm -it --network host ransomware-agent
