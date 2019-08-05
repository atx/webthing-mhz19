#! /usr/bin/env python3

import asyncio
import argparse
import serial_asyncio
import struct

from webthing import Property, SingleThing, Thing, Value, WebThingServer


class MHZ19(asyncio.Protocol, Thing):

    def __init__(self):
        super().__init__(
            "urn:dev:ops:co2",
            "CO2 sensor",
            ["MultiLevelSensor", "MultiLevelSensor"],
            "MHZ17 CO2 sensor"
        )
        self.ppm = Value(None)
        self.add_property(
            Property(
                self,
                "ppm",
                self.ppm,
                metadata={
                    "@type": "LevelProperty",
                    "title": "CO2 PPM",
                    "type": "number",
                    "description": "CO2 PPM concentration",
                    "minimum": 0,
                    "maximum": 5000,
                    "unit": "ppm",
                    "readOnly": True,
                }
            )
        )
        self.temperature = Value(None)
        self.add_property(
            Property(
                self,
                "temperature",
                self.temperature,
                metadata={
                    "@type": "LevelProperty",
                    "title": "Temperature",
                    "type": "number",
                    "description": "Temperature",
                    "minimum": -40,
                    "maximum": 100,
                    "unit": "celsius",
                    "readOnly": True,
                }
            )
        )

    @staticmethod
    def calculate_checksum(packet):
        assert len(packet) == 8
        cs = 0
        for b in packet[1:]:
            cs = (cs + b) % 256
        cs = 0xff - cs + 1
        return cs

    async def _update_task(self):
        while True:
            self.transport.write(
                bytes([0xff, 0x01, 0x86, 0x00, 0x00, 0x00, 0x00, 0x00, 0x79])
            )
            await asyncio.sleep(5)

    def connection_made(self, transport):
        self.transport = transport
        self.buff = bytearray()
        print("Port open, starting update task")
        asyncio.get_event_loop().create_task(self._update_task())
        self.measurement_count = 0

    def process_packet(self, packet):
        assert packet[0] == 0xff
        cs = self.calculate_checksum(packet[:-1])
        if cs != packet[-1]:
            print("Invalid checksum ({:02x} != {:02x})".format(cs, packet[-1]))
            return  # Drop the packet

        if packet[1] == 0x86:
            self.measurement_count += 1
            # Measurement
            _, _, ppm, temp, _, _, _ = struct.unpack(">bbHBBHB", packet)
            temp = temp - 40
            # Weirdly enough, my status, unknown is always
            print("PPM = {}, Temperature = {}".format(ppm, temp))
            if self.measurement_count < 20:
                # This is needed because the sensor takes some time to
                # stabilize
                return
            self.ppm.notify_of_external_update(ppm)
            self.temperature.notify_of_external_update(temp)

    def data_received(self, data):
        for byte in data:
            if not self.buff:
                # Search for start byte
                if byte == 0xff:
                    self.buff.append(byte)
            else:
                self.buff.append(byte)
                if len(self.buff) == 9:
                    self.process_packet(self.buff)
                    self.buff.clear()

    def connection_lost(self, exc):
        print("Connection lost")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--serial", default="/dev/ttyUSB0")
    parser.add_argument("-p", "--port", type=int, default=8003)
    args = parser.parse_args()

    loop = asyncio.get_event_loop()
    coro = serial_asyncio.create_serial_connection(loop, MHZ19, args.serial,
                                                   baudrate=9600)
    _, thing = loop.run_until_complete(coro)
    server = WebThingServer(SingleThing(thing), port=args.port)
    server.start()
