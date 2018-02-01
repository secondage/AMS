#!/usr/bin/env python
# coding: utf-8

from sys import float_info
from time import time

from ams import Topic, Schedule, Route
from ams.nodes import Vehicle, TrafficSignal
from ams.messages import TrafficSignalStatus, VehicleStatus

from pprint import PrettyPrinter
pp = PrettyPrinter(indent=2).pprint


class SimCar(Vehicle):
    LOWER_INTER_VEHICLE_DISTANCE = 3.0
    LOWER_INTER_TRAFFIC_SIGNAL_DISTANCE = 1.0
    FLOAT_MAX = float_info.max
    ACCELERATION_MAX = 0.3  # [m/s^2]

    def __init__(self, name, waypoint, arrow, route, intersection, waypoint_id, arrow_code, velocity, schedules=None, dt=1.0):
        super().__init__(name, waypoint, arrow, route, waypoint_id, arrow_code, velocity, schedules, dt)

        self.topicTrafficSignalStatus = Topic()
        self.topicTrafficSignalStatus.set_root(TrafficSignal.TOPIC.PUBLISH)

        self.__prev_waypoint_id = waypoint_id

        self.traffic_signals = {}
        self.other_vehicles = {}

        self.intersection = intersection

        self.add_on_message_function(self.update_other_vehicles)
        self.add_on_message_function(self.update_traffic_signals)

        self.set_subscriber(self.topicStatus.all)
        self.set_subscriber(self.topicTrafficSignalStatus.all)

    def update_traffic_signals(self, _client, _user_data, topic, payload):
        if self.topicTrafficSignalStatus.root in topic:
            traffic_signal_status = TrafficSignalStatus.get_data(**self.topicTrafficSignalStatus.unserialize(payload))
            self.traffic_signals[traffic_signal_status["route_code"]] = traffic_signal_status

    def update_other_vehicles(self, _client, _user_data, topic, payload):
        if self.topicStatus.private not in topic and \
                self.topicStatus.root in topic:
            vehicle_id = self.topicStatus.get_id(topic)
            vehicle_status = VehicleStatus.get_data(**self.topicStatus.unserialize(payload))

            # todo: localize
            self.other_vehicles[vehicle_id] = vehicle_status

    def get_monitored_route(self, distance=100.0):
        if distance <= 0:
            return None
        # return self.schedules[0].route
        arrow_codes = self.schedules[0].route.arrow_codes
        arrow_codes = arrow_codes[arrow_codes.index(self.arrow_code):]
        route = Route.get_route(
            self.waypoint_id,
            self.arrow.get_waypoint_ids(self.schedules[0].route.arrow_codes[-1])[-1],
            arrow_codes)
        return self.route.get_sliced_route(route, distance)

    def __get_inter_vehicle_distance(self, monitored_route):
        monitored_waypoint_ids = self.route.get_route_waypoint_ids(monitored_route)
        inter_vehicle_distance = SimCar.FLOAT_MAX
        if self.arrow_code is not None and 0 < len(self.other_vehicles):
            other_vehicles_waypoint_ids = list(map(
                lambda x: x.location.waypoint_id, self.other_vehicles.values()))
            for i, monitored_waypoint_id in enumerate(monitored_waypoint_ids):
                if monitored_waypoint_id in other_vehicles_waypoint_ids:
                    inter_vehicle_distance = self.route.get_distance_of_waypoints(monitored_waypoint_ids[:i+1])
                    break
        # print("inter_vehicle_distance {}[m]".format(inter_vehicle_distance))
        return inter_vehicle_distance

    def __get_inter_traffic_signal_distance(self, monitored_route):
        monitored_arrow_codes = monitored_route.arrow_codes
        inter_traffic_signal_distance = SimCar.FLOAT_MAX

        not_green_traffic_signal_route_codes = list(map(
            lambda x: x["route_code"], filter(
                lambda x: x["state"] in [TrafficSignal.STATE.YELLOW, TrafficSignal.STATE.RED],
                self.traffic_signals.values())))

        new_monitored_route = None
        for i, monitored_arrow_code in enumerate(monitored_arrow_codes):
            for not_green_traffic_signal_route_code in not_green_traffic_signal_route_codes:
                if monitored_arrow_code in not_green_traffic_signal_route_code:
                    start_waypoint_id, arrow_codes, _ = self.route.split_route_code(not_green_traffic_signal_route_code)
                    if monitored_arrow_code == arrow_codes[0]:
                        waypoint_ids = self.arrow.get_waypoint_ids(monitored_arrow_code)
                        if self.waypoint_id not in waypoint_ids or \
                                waypoint_ids.index(self.waypoint_id) <= waypoint_ids.index(start_waypoint_id):
                            new_monitored_route = Route.get_route(
                                monitored_route.start_waypoint_id, start_waypoint_id, monitored_arrow_codes[:i+1])
                            break
            if new_monitored_route is not None:
                break

        if new_monitored_route is not None:
            inter_traffic_signal_distance = self.route.get_route_length(new_monitored_route)

        # print("inter_traffic_signal_distance {}[m]".format(inter_traffic_signal_distance))
        return inter_traffic_signal_distance

    def __get_movable_distance(self):
        movable_distance = SimCar.FLOAT_MAX
        if 0 < len(self.schedules):
            if self.schedules[0].event == Vehicle.ACTION.MOVE:
                # check inter-vehicle distance
                monitored_route = self.get_monitored_route()
                if monitored_route is None:
                    return 0.0
                inter_vehicle_distance = self.__get_inter_vehicle_distance(monitored_route)
                movable_distance = inter_vehicle_distance - SimCar.LOWER_INTER_VEHICLE_DISTANCE

                # check inter-trafficSignal distance
                monitored_route = self.get_monitored_route(movable_distance)
                if monitored_route is None:
                    return 0.0
                inter_traffic_signal_distance = self.__get_inter_traffic_signal_distance(monitored_route)
                movable_distance = min(
                    movable_distance, inter_traffic_signal_distance - SimCar.LOWER_INTER_TRAFFIC_SIGNAL_DISTANCE)

        return movable_distance

    def update_pose(self):
        movable_distance = self.__get_movable_distance()
        delta_distance = min(self.velocity * self.dt, movable_distance)
        if 0.0 < delta_distance:
            self.__prev_waypoint_id = self.waypoint_id
            self.position, self.yaw, self.arrow_code, self.waypoint_id = self.get_next_pose(delta_distance)

    def is_achieved(self):
        return self.waypoint_id == self.schedules[0].route.goal_waypoint_id

    def get_next_pose(self, delta_distance):
        position, waypoint_id, arrow_code = self.route.get_moved_position(
            self.position, delta_distance, self.schedules[0].route)
        yaw = self.arrow.get_yaw(arrow_code, waypoint_id)
        return position, yaw, arrow_code, waypoint_id

    def update_velocity(self):
        speed_limit = self.waypoint.get_speed_limit(self.waypoint_id)
        if self.velocity < speed_limit:
            self.velocity += min(SimCar.ACCELERATION_MAX * self.dt, speed_limit - self.velocity)
        elif speed_limit < self.velocity:
            self.velocity = speed_limit
        return

    def update_status(self):
        current_time = time()
        if self.state == Vehicle.STATE.STOP:
            if self.schedules[0].event == Vehicle.ACTION.MOVE:
                self.state = Vehicle.STATE.MOVE
            else:
                if self.schedules[0].period.end <= current_time:
                    if 1 < len(self.schedules):
                        self.schedules.pop(0)

                        # update next schedule
                        dif_time = current_time - self.schedules[0].period.start
                        self.schedules = Schedule.get_shifted_schedules(self.schedules, dif_time)

                        self.state = Vehicle.STATE.MOVE

        elif self.state == Vehicle.STATE.MOVE:
            self.update_pose()
            self.update_velocity()
            if self.is_achieved():
                self.waypoint_id = self.schedules[0].route.goal_waypoint_id
                self.arrow_code = self.schedules[0].route.arrow_codes[-1]
                self.position = self.waypoint.get_position(self.waypoint_id)
                self.yaw = self.arrow.get_yaw(self.arrow_code, self.waypoint_id)
                self.schedules.pop(0)

                # update next schedule
                new_start_time = time()
                dif_time = new_start_time - self.schedules[0].period.start
                self.schedules = Schedule.get_shifted_schedules(self.schedules, dif_time)

                self.state = Vehicle.STATE.STOP
