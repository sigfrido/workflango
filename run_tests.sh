#!/bin/bash

SRCDIR=$(dirname "$(realpath "${BASH_SOURCE[0]}")")
cd $SRCDIR

./manage.py test
cd testproject
./manage.py test
cd ..
