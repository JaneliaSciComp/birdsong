#!/bin/sh

docker-compose -f docker-compose-prod.yml down
docker image ls | grep registry.int.janelia.org | awk '{print $3}' | xargs docker image rm
docker volume rm assignment-manager_static_volume
docker pull registry.int.janelia.org/flyem/assignment-manager
docker-compose -f docker-compose-prod.yml up
