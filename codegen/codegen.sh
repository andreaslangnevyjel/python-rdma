#!/bin/bash

./mkstructs.py -x iba_transport.xml -x iba_12.xml -x iba_13_4.xml -x iba_13_6.xml -x iba_14.xml -x iba_15.xml -x iba_16_1.xml -x iba_16_3.xml -x iba_16_4.xml -x iba_16_5.xml -o ../rdma/IBA_struct.py -r ../doc/iba_struct.inc
