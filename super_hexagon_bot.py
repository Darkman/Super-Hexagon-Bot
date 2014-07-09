#!/usr/bin/env python3

from sys import byteorder
from struct import pack, unpack
from ctypes import windll, c_char_p, c_ulong, byref, c_int, c_ubyte

# window api
import win32ui
import win32process


class Memory:
    OpenProcess = windll.kernel32.OpenProcess
    ReadProcessMemory = windll.kernel32.ReadProcessMemory
    WriteProcessMemory = windll.kernel32.WriteProcessMemory
    CloseHandle = windll.kernel32.CloseHandle

    PROCESS_ALL_ACCESS = 0x1F0FFF

    def __init__(self, pid):
        self.process_handle = self.OpenProcess(self.PROCESS_ALL_ACCESS, False, pid)

        self.buffer = c_char_p(b"data buffer")
        self.buffer_size = len(self.buffer.value)
        self.bytes_read = c_ulong(0)
        self.bytes_written = c_ulong(0)

    def read_app_base(self, address):
        app_base = c_int()
        self.ReadProcessMemory(self.process_handle, address, byref(app_base), 4, byref(self.bytes_read))
        return app_base.value

    def read(self, address):
        self.ReadProcessMemory(self.process_handle, address, self.buffer, self.buffer_size, byref(self.bytes_read))
        value = int.from_bytes(self.buffer.value, byteorder=byteorder)
        return value

    def read_bytes(self, address, size):
        buffer = (c_ubyte * size)()
        self.ReadProcessMemory(self.process_handle, address, byref(buffer), size, byref(self.bytes_read))
        return b''.join(pack('<B', buffer[i]) for i in range(size))

    def write(self, address, value):
        value = int(value)
        value = c_ulong(value)
        self.WriteProcessMemory(self.process_handle, address, byref(value), 4, byref(self.bytes_written))
        return self.bytes_written

    def close_handle(self):
        self.CloseHandle(self.process_handle)
        return True


class SuperHexagon:
    def __init__(self, memory):
        self.memory = memory

        self.base_pointer = 0x694B00

        # Relative game memory location offsets.
        self.offsets = {'num_slots': 0x1BC,
                        'num_walls': 0x2930,
                        'first_wall': 0x220,
                        'player_angle': 0x2958,
                        'player_angle_2': 0x2954,
                        'mouse_down_left': 0x42858,
                        'mouse_down_right': 0x4285A,
                        'mouse_down': 0x42C45,
                        'world_angle': 0x1AC
                        }

        self.app_base = self.memory.read_app_base(self.base_pointer)

    def get_walls(self):
        wall_list = []
        offset = self.offsets['first_wall']
        num_walls = self.get_num_walls()
        for index in range(num_walls):
            # Read wall for wall. Could also read the entire thing in one big chunk
            # and then get the walls_data from chunk[index*0x14:i*0x14+0x14].
            address = self.app_base + offset + index * 0x14
            wall_data = self.memory.read_bytes(address, 0x14)
            wall = {
                'slot':     unpack('<i', wall_data[0: 4])[0],
                'distance': unpack('<i', wall_data[4: 8])[0],
                'width':    unpack('<i', wall_data[8:12])[0]
            }
            wall_list.append(wall)
        return wall_list

    def get_player_angle(self):
        offset = self.offsets['player_angle']
        player_angle = self.memory.read(self.app_base + offset)
        return player_angle

    def get_player_slot(self):
        angle = self.get_player_angle()
        num_slots = self.get_num_slots()
        player_slot = angle / 360.0 * num_slots
        player_slot = round(player_slot, 1)
        return player_slot

    def get_world_angle(self):
        offset = self.offsets['world_angle']
        world_angle = self.memory.read(self.app_base + offset)
        return world_angle

    def get_num_slots(self):
        offset = self.offsets['num_slots']
        num_slots = self.memory.read(self.app_base + offset)
        return num_slots

    def get_num_walls(self):
        """
        Read the game memory location for the
        number of walls currently on the playing field.
        """
        offset = self.offsets['num_walls']
        num_walls = self.memory.read(self.app_base + offset)
        return num_walls

    def get_first_wall(self):
        offset = self.offsets['first_wall']
        first_wall = self.memory.read(self.app_base + offset)
        return first_wall

    ## Movement functions
    def start_moving_left(self):
        self.memory.write(self.app_base + self.offsets['mouse_down_left'], 1)
        self.memory.write(self.app_base + self.offsets['mouse_down'], 1)

    def start_moving_right(self):
        self.memory.write(self.app_base + self.offsets['mouse_down_right'], 1)
        self.memory.write(self.app_base + self.offsets['mouse_down'], 1)

    def stop_moving(self):
        self.memory.write(self.app_base + self.offsets['mouse_down_left'], 0)
        self.memory.write(self.app_base + self.offsets['mouse_down_right'], 0)
        self.memory.write(self.app_base + self.offsets['mouse_down'], 0)

    ## Testing functions. Should use normal movement instead of writing memory.
    def set_player_slot(self, slot):
        num_slots = self.get_num_slots()
        angle = 360 / num_slots * (slot % num_slots) + (180 / num_slots)
        self.memory.write(self.app_base + self.offsets['player_angle'], angle)
        self.memory.write(self.app_base + self.offsets['player_angle_2'], angle)

    def set_world_angle(self, angle):
        self.memory.write(self.app_base + self.offsets['world_angle'], angle)


class Logic:
    def __init__(self, hexagon):
        self.hexagon = hexagon
        self.target_slot = None

    def nope(self):
        """
        Seems to work most of the time, but makes a mistake quite
        often when dealing with horseshoe shaped patterns.
        Suggest using start method instead, this is only here to test later.
        """
        while True:
            wall_list = self.hexagon.get_walls()
            min_distances = {}
            num_slots = self.hexagon.get_num_slots()
            for wall in wall_list:
                if 0 < wall['distance'] < 1000000 and wall['width'] > 0 and -1 < wall['slot'] < num_slots:
                    if wall['slot'] in min_distances:
                        min_distances[wall['slot']] = min(min_distances[wall['slot']], wall['distance'])
                    else:
                        min_distances[wall['slot']] = wall['distance']
            if min_distances:
                target_slot = max(min_distances.keys(), key=(lambda key: min_distances[key]))
                self.hexagon.set_player_slot(target_slot)

    def start(self):
        """
        Autonomously play Super Hexagon by calculating the correct
        slot and setting the player position to it in memory.
        """
        while True:
            wall_list = self.hexagon.get_walls()
            num_slots = self.hexagon.get_num_slots()
            data = {}

            for wall in wall_list:
                slot = wall['slot']
                distance = wall['distance']
                width = wall['width']
                if 0 < distance < 1000000 and width > 0 and -1 < slot < num_slots:
                    if slot in data:
                        if distance < data[slot]:
                            data[slot] = distance
                    else:
                        data[slot] = distance
            if data:
                target_slot = max(data.keys(), key=(lambda key: data[key]))
                # TODO: Move the position of the player correctly instead of writing memory.
                self.hexagon.set_player_slot(target_slot)

    def no_spin(self):
        """
        Continually sets the hexagon world to a certain angle.
        This stops the hexagon field from spinning around.
        """
        while True:
            self.hexagon.set_world_angle(0)


def main():
    # Find Super Hexagon process id by searching window names
    window_handle = win32ui.FindWindow(None, u"Super Hexagon").GetSafeHwnd()
    pid = win32process.GetWindowThreadProcessId(window_handle)[1]

    memory = Memory(pid)
    hexagon = SuperHexagon(memory)
    logic = Logic(hexagon)
    logic.start()
    memory.close_handle()

if __name__ == '__main__':
    main()
