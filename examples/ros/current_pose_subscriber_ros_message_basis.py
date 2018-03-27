#!/usr/bin/env python
# coding: utf-8

from argparse import ArgumentParser

from ams.ros import CurrentPoseSubscriber


parser = ArgumentParser()
parser.add_argument("-H", "--host", type=str, default="localhost", help="host")
parser.add_argument("-P", "--port", type=int, default=1883, help="port")
parser.add_argument("-ID", "--id", type=str, required=True, help="node id")
parser.add_argument("-PS", "--period", type=float, default=1.0, help="period second")
args = parser.parse_args()


if __name__ == '__main__':

    currentPoseSubscriber = CurrentPoseSubscriber(_id=args.id, period=args.period)

    print("currentPoseSubscriber {} on {}".format(
        currentPoseSubscriber.event_loop_id, currentPoseSubscriber.get_pid()))

    currentPoseSubscriber.start(host=args.host, port=args.port)