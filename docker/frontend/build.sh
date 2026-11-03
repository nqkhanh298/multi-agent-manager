#!/bin/sh
set -eu
ln -s /opt/m3/node_modules /workspace/node_modules
trap 'rm /workspace/node_modules' EXIT
cd /workspace
npm run build
