import logging

from flask import g, session

from .db_serializable import (
    DbError, DeletionError, Identifiable, QueryHelper, Serializable, coldef)
from .item import Item
from .pile import Pile
from .progress import Progress
from .utils import NumTup, RequestHelper

logger = logging.getLogger(__name__)
tables_to_create = {
    'locations': f"""
        {coldef('name')},
        toplevel boolean NOT NULL,
        masked boolean NOT NULL,
        progress_id integer,
        quantity float(4) NOT NULL,
        dimensions integer[2],
        excluded integer[4],
        FOREIGN KEY (game_token, progress_id)
            REFERENCES progress (game_token, id)
            DEFERRABLE INITIALLY DEFERRED
        """
    }

class ItemAt(Pile):
    def __init__(self, item, loc):
        super().__init__(item=item, container=loc)
        self.position = NumTup((0, 0))

    @classmethod
    @property
    def container_type(cls):
        return Location.typename

    def _base_export_data(self):
        """Prepare the base dictionary for JSON and DB."""
        return {
            'item_id': self.item.id,
            'quantity': self.quantity,
            }

    def dict_for_json(self):
        data = self._base_export_data()
        data.update({
            'position': self.position.as_list(),
            })
        return data

    def dict_for_main_table(self):
        data = self._base_export_data()
        data.update({
            'position': self.position,
            })
        return data

    @classmethod
    def from_data(cls, data, loc=None):  #pylint: disable=arguments-differ
        data = cls.prepare_dict(data)
        instance = cls(None, loc)
        instance.set_basic_data(data)
        instance.item = Item(instance.item_id)
        instance.position = NumTup(data.get('position', (0, 0)))
        return instance

class Destination(Serializable):
    def __init__(self, loc):
        super().__init__()
        self.loc = loc
        self.distance = 1
        self.exit = (0, 0)  # in loc coming from
        self.entrance = (0, 0)  # in dest loc

    def _base_export_data(self):
        """Prepare the base dictionary for JSON and DB."""
        return {
            'dest_id': self.loc.id,
            'distance': self.distance,
            }

    def dict_for_json(self):
        data = self._base_export_data()
        data.update({
            'exit': self.exit.as_list(),
            'entrance': self.entrance.as_list(),
            })
        return data

    def dict_for_main_table(self):
        data = self._base_export_data()
        data.update({
            'exit': self.exit,
            'entrance': self.entrance,
            })
        return data

    @classmethod
    def from_data(cls, data):
        data = cls.prepare_dict(data)
        dest_id = int(data.get('dest_id', 0))
        instance = cls(Location(dest_id))
        instance.distance = data.get('distance', 0)
        instance.exit = NumTup(data.get('exit', (0, 0)))
        instance.entrance = NumTup(data.get('entrance', (0, 0)))
        return instance

class Grid:
    def __init__(self):
        self.dimensions = NumTup((0, 0))  # width, height
        self.excluded = NumTup((0, 0, 0, 0))  # left, top, right, bottom
        self.default_pos = None  # legal position in grid if any

    def set_default_pos(self):
        """Returns None if there are no legal positions.
        Call this method whenever changing dimensions or excluded.
        """
        width, height = self.dimensions.as_tuple()
        left, top, right, bottom = self.excluded.as_tuple()
        for y in range(1, height + 1):
            for x in range(1, width + 1):
                if not (left <= x <= right and top <= y <= bottom):
                    self.default_pos = NumTup((x, y))
                    return
        self.default_pos = None

    def in_grid(self, pos):
        """Returns True if position is legally in the grid."""
        if not pos:
            return False
        x, y = pos
        width, height = self.dimensions.as_tuple()
        left, top, right, bottom = self.excluded.as_tuple()
        if x < 1 or x > width:
            return False
        if y < 1 or y > height:
            return False
        if left <= x <= right and top <= y <= bottom:
            return False
        return True

class Location(Identifiable):
    def __init__(self, new_id=""):
        super().__init__(new_id)
        self.name = ""
        self.description = ""
        self.toplevel = False
        self.masked = False
        self.destinations = {}  # Destination objects keyed by loc id
        self.items = {}  # ItemAt objects keyed by item id
        # producing local items? Maybe char would do that.
        self.progress = Progress(container=self)
        self.pile = Pile()  # for Progress
        self.grid = Grid()

    @classmethod
    @property
    def typename(cls):
        return 'loc'

    def _base_export_data(self):
        """Prepare the base dictionary for JSON and DB."""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'toplevel': self.toplevel,
            'masked': self.masked,
            'quantity': self.pile.quantity,
            }

    def dict_for_json(self):
        data = self._base_export_data()
        data.update({
            'destinations': [
                dest.dict_for_json()
                for dest in self.destinations.values()],
            'items': [
                item_at.dict_for_json()
                for item_at in self.items.values()],
            'progress': self.progress.dict_for_json(),
            'dimensions': self.grid.dimensions.as_list(),
            'excluded': self.grid.excluded.as_list()
            })
        return data

    def dict_for_main_table(self):
        data = self._base_export_data()
        data.update({
            'progress_id': self.progress.id or None,
            'dimensions': self.grid.dimensions,
            'excluded': self.grid.excluded
            })
        return data

    @classmethod
    def from_data(cls, data):
        data = cls.prepare_dict(data)
        instance = super().from_data(data)
        instance.toplevel = data.get('toplevel', False)
        instance.masked = data.get('masked', False)
        for dest_data in data.get('destinations', []):
            if not isinstance(dest_data, dict):
                dest_data = vars(dest_data)
            instance.destinations[
                dest_data.get('dest_id', 0)] = Destination.from_data(dest_data)
        for item_data in data.get('items', []):
            if not isinstance(item_data, dict):
                item_data = vars(item_data)
            item_at = ItemAt.from_data(item_data, instance)
            instance.items[item_data.get('item_id', 0)] = item_at
        instance.pile = Pile()
        instance.pile.quantity = data.get('quantity', 0.0)
        instance.progress = Progress.from_data(
            data.get('progress', {}), instance)
        instance.grid.dimensions = NumTup(data.get('dimensions', (0, 0)))
        instance.grid.excluded = NumTup(data.get('excluded', (0, 0, 0, 0)))
        instance.grid.set_default_pos()
        return instance

    def to_db(self):
        logger.debug("to_db()")
        self.progress.to_db()
        super().to_db()
        for rel_table in ('loc_destinations', 'loc_items'):
            self.execute_change(f"""
                DELETE FROM {rel_table}
                WHERE loc_id = %s AND game_token = %s
                """, (self.id, g.game_token))
        if self.destinations:
            values = []
            for dest in self.destinations.values():
                values.append((
                    g.game_token, self.id,
                    dest.loc.id,
                    dest.distance,
                    dest.exit.as_pg_array(),
                    dest.entrance.as_pg_array(),
                    ))
            self.insert_multiple(
                "loc_destinations",
                "game_token, loc_id, dest_id, distance, exit, entrance",
                values)
        if self.items:
            values = []
            for item_id, item_at in self.items.items():
                values.append((
                    g.game_token, self.id,
                    item_id,
                    item_at.quantity,
                    item_at.position.as_pg_array(),
                    ))
            self.insert_multiple(
                "loc_items",
                "game_token, loc_id, item_id, quantity, position",
                values)

    def unmask(self):
        """Mark this location as visited if it hasn't been yet."""
        if self.id:
            self.execute_change("""
                UPDATE locations
                SET masked = false
                WHERE id = %s AND masked = true
                """, (self.id,))

    @classmethod
    def load_complete_objects(cls, id_to_get=None):
        """Load objects with everything needed for storing to db
        or JSON file.
        :param id_to_get: specify to only load a single object
        """
        logger.debug("load_complete_objects(%s)", id_to_get)
        if id_to_get in ['new', '0', 0]:
            return cls()
        locs = Progress.load_base_data(cls, id_to_get)
        # Get destination data
        qhelper = QueryHelper("""
            SELECT *
            FROM loc_destinations
            WHERE game_token = %s
            """, [g.game_token])
        qhelper.add_limit("loc_id", id_to_get)
        dest_rows = cls.execute_select(qhelper=qhelper)
        for row in dest_rows:
            loc = locs[row.loc_id]
            loc.setdefault('destinations', []).append(row)
        # Get this location's item relation data
        qhelper = QueryHelper("""
            SELECT *
            FROM loc_items
            WHERE game_token = %s
            """, [g.game_token])
        qhelper.add_limit("loc_id", id_to_get)
        item_rows = cls.execute_select(qhelper=qhelper)
        for row in item_rows:
            loc = locs[row.loc_id]
            loc.setdefault('items', []).append(row)
        # Set list of objects
        instances = []
        for data in locs.values():
            instances.append(cls.from_data(data))
        if id_to_get:
            return instances[0]
        g.game_data.set_list(cls, instances)
        return instances

    @classmethod
    def data_for_configure(cls, id_to_get):
        logger.debug("data_for_configure(%s)", id_to_get)
        current_obj = cls.load_complete_objects(id_to_get)
        # Replace partial objects with fully populated objects
        g.game_data.from_db_flat([Location, Item])
        for dest_id, dest in current_obj.destinations.items():
            dest.loc = Location.get_by_id(dest_id)
        for item_at in current_obj.items.values():
            item_at.item = Item.get_by_id(item_at.item.id)
            if not current_obj.grid.in_grid(item_at.position):
                item_at.position = current_obj.grid.default_pos
        return current_obj

    @classmethod
    def data_for_play(cls, id_to_get):
        logger.debug("data_for_play(%s)", id_to_get)
        current_obj = cls.data_for_configure(id_to_get)
        from .character import Character
        chars = Character.load_characters_at_loc(id_to_get)
        for char in chars:
            if char.location.id == current_obj.id:
                if not current_obj.grid.in_grid(char.position):
                    char.position = current_obj.grid.default_pos
        from .event import Event
        Event.load_triggers_for_type(id_to_get, cls.typename)
        return current_obj

    def configure_by_form(self):
        req = RequestHelper('form')
        if req.has_key('save_changes') or req.has_key('make_duplicate'):
            req.debug()
            entity_list = self.get_list()
            if self not in entity_list:
                entity_list.append(self)
            self.name = req.get_str('location_name')
            self.description = req.get_str('location_description')
            self.toplevel = req.get_bool('top_level')
            req = RequestHelper('form')
            self.masked = req.get_bool('masked')
            self.grid.dimensions = req.get_numtup(
                'dimensions', (0, 0), delim='x')
            self.grid.excluded = (
                req.get_numtup('excluded_left_top', (0, 0)) +
                req.get_numtup('excluded_right_bottom', (0, 0))
                )
            self.grid.set_default_pos()
            self.destinations = {}
            for dest_id, dest_dist, dest_exit, dest_entrance in zip(
                    req.get_list('dest_id[]'),
                    req.get_list('dest_distance[]'),
                    req.get_list('dest_exit[]'),
                    req.get_list('dest_entrance[]')
                    ):
                dest = Destination(Location(dest_id))
                dest.distance = int(dest_dist)
                dest.exit = NumTup.from_str(dest_exit, (0, 0))
                dest.entrance = NumTup.from_str(dest_entrance, (0, 0))
                self.destinations[dest_id] = dest
            self.items = {}
            old = Location.load_complete_objects(self.id)
            for item_id, item_qty, item_pos in zip(
                    req.get_list('item_id[]'),
                    req.get_list('item_qty[]'),
                    req.get_list('item_pos[]')
                    ):
                item_at = ItemAt(Item(int(item_id)), self)
                item_at.position = NumTup.from_str(item_pos, (0, 0))
                old_item = old.items.get(item_id, None)
                old_qty = old_item.quantity if old_item else 0
                item_at.quantity = req.set_num_if_changed(item_qty, old_qty)
                self.items[item_id] = item_at
            self.to_db()
        elif req.has_key('delete_location'):
            try:
                self.remove_from_db()
                session['file_message'] = 'Removed location.'
            except DbError as e:
                raise DeletionError(str(e))
        elif req.has_key('cancel_changes'):
            logger.debug("Cancelling changes.")
        else:
            logger.debug("Neither button was clicked.")
