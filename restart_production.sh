#!/bin/sh

sudo docker-compose -f docker-compose.yml down
sudo docker image ls | grep birdsong_app | awk '{print $3}' | xargs sudo docker image rm
#sudo docker volume rm assignment-manager_static_volume
##sudo docker pull registry.int.janelia.org/flyem/assignment-manager
#sudo docker-compose -f docker-compose.yml up
