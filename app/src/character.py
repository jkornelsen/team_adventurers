from flask import g, session
import logging

from .attrib import Attrib, AttribOf
from .db_serializable import Identifiable, MutableNamespace, coldef
from .item import Item
from .location import Destination, Location
from .progress import Progress
from .utils import Pile, RequestHelper, Storage

tables_to_create = {
    'characters': f"""
        {coldef('id')},
        {coldef('name')},
        {coldef('description')},
        toplevel boolean NOT NULL,
        masked boolean NOT NULL,
        progress_id integer,
        quantity float(4) NOT NULL,
        location_id integer,
        dest_id integer,
        position integer[2],
        FOREIGN KEY (game_token, progress_id)
            REFERENCES progress (game_token, id)
    """,
}
logger = logging.getLogger(__name__)

class OwnedItem(Pile):
    PILE_TYPE = Storage.CARRIED
    def __init__(self, item=None, char=None):
        super().__init__(item, char)
        self.slot = ''  # for example, "main hand"

    def to_json(self):
        return {
            'item_id': self.item.id,
            'quantity': self.quantity,
            'slot': self.slot,
        }

    @classmethod
    def from_json(cls, data, char=None):
        instance = cls(Item(int(data.get('item_id', 0))), char)
        instance.quantity = data.get('quantity', 0)
        instance.slot = data.get('slot', "")
        return instance

    def equipped(self):
        """If not equipped (worn or held), then it's assumed to be carried in
        inventory, such as a backpack."""
        return bool(self.slot)

class Character(Identifiable):
    def __init__(self, new_id=""):
        super().__init__(new_id)
        self.name = ""
        self.description = ""
        self.toplevel = True
        self.masked = False
        self.attribs = {}  # AttribOf objects keyed by attrib id
        self.items = {}  # OwnedItem objects keyed by item id
        self.location = None  # Location object where char is
        self.position = (0, 0)  # grid coordinates: top, left
        self.destination = None  # Location object to travel to
        self.progress = None  # travel or producing items
        self.pile = None  # for Progress

    def to_json(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'toplevel': self.toplevel,
            'masked': self.masked,
            'attribs': {
                str(attrib_id): attrib_of.val
                for attrib_id, attrib_of in self.attribs.items()},
            'items': [
                owned.to_json() for owned in self.items.values()],
            'location_id': self.location.id if self.location else None,
            'position': self.position,
            'progress': self.progress.to_json(),
            'quantity': self.pile.quantity,
            'dest_id': self.destination.id if self.destination else None
        }

    @classmethod
    def from_json(cls, data):
        """Looks for attribs and locations in g.game_data with get_by_id(),
        so consider loading those before calling this method.
        """
        if not isinstance(data, dict):
            data = vars(data)
        instance = cls(int(data.get('id', 0)))
        instance.name = data.get('name', "")
        instance.description = data.get('description', '')
        instance.toplevel = data.get('toplevel', False)
        instance.masked = data.get('masked', False)
        for owned_data in data.get('items', []):
            if not isinstance(owned_data, dict):
                owned_data = vars(owned_data)
            instance.items[owned_data.get('item_id', 0)] = OwnedItem.from_json(
                owned_data, instance)
        instance.attribs = {
            attrib_id: AttribOf(
                Attrib.get_by_id(int(attrib_id)), val=val)
            for attrib_id, val in data.get('attribs', {}).items()}
        instance.location = Location.get_by_id(
            int(data['location_id'])) if data.get('location_id', 0) else None
        instance.position = data.get('position', (0, 0))
        instance.pile = Pile()
        instance.pile.quantity = data.get('quantity', 0.0)
        instance.progress = Progress.from_json(
            data.get('progress', {}), instance)
        instance.destination = Location.get_by_id(
            int(data['dest_id'])) if data.get('dest_id', 0) else None
        return instance

    def json_to_db(self, doc):
        logger.debug("json_to_db()")
        self.progress.json_to_db(doc['progress'])
        doc['progress_id'] = self.progress.id
        super().json_to_db(doc)
        for rel_table in ('char_attribs', 'char_items'):
            self.execute_change(f"""
                DELETE FROM {rel_table}
                WHERE char_id = %s AND game_token = %s
            """, (self.id, self.game_token))
        if doc['attribs']:
            values = [
                (g.game_token, self.id, attrib_id, val)
                for attrib_id, val in doc['attribs'].items()]
            self.insert_multiple(
                "char_attribs",
                "game_token, char_id, attrib_id, value",
                values)
        if doc['items']:
            logger.debug("items: %s", doc['items'])
            values = []
            for owned_item in doc['items']:
                values.append((
                    g.game_token, self.id,
                    owned_item['item_id'],
                    owned_item['quantity'],
                    owned_item['slot']
                    ))
            self.insert_multiple(
                "char_items",
                "game_token, char_id, item_id, quantity, slot",
                values)

    @classmethod
    def load_characters_at_loc(cls, loc_id, load=True):
        query = """
            SELECT *
            FROM characters
            WHERE game_token = %s
        """
        values = [g.game_token]
        if loc_id:
            query += " AND location_id = %s"
            values.append(loc_id)
        query += "\nORDER BY name"
        chars = []
        characters_rows = cls.execute_select(query, values)
        for char_row in characters_rows:
            chars.append(Character.from_json(char_row))
        if load:
            g.game_data.set_list(Character, chars)
        return chars

    @classmethod
    def load_complete_object(cls, id_to_get):
        """Load an object with everything needed for storing to db."""
        logger.debug("load_complete_object(%s)", id_to_get)
        if id_to_get == 'new':
            id_to_get = 0
        else:
            id_to_get = int(id_to_get)
        # Get this character's base data and progress data
        tables_row = cls.select_tables("""
            SELECT *
            FROM {tables[0]}
            LEFT JOIN {tables[1]}
                ON {tables[1]}.id = {tables[0]}.progress_id
                AND {tables[1]}.game_token = {tables[0]}.game_token
            WHERE {tables[0]}.game_token = %s
                AND {tables[0]}.id = %s
        """, (g.game_token, id_to_get), ['characters', 'progress'],
            fetch_all=False)
        current_data = MutableNamespace()
        if tables_row:
            char_data, progress_data = tables_row
            current_data = char_data
            char_data.progress = progress_data
        # Get this character's attrib relation data
        char_attribs_rows = cls.execute_select("""
            SELECT *
            FROM char_attribs
            WHERE game_token = %s
                AND char_id = %s
        """, (g.game_token, id_to_get))
        for attrib_data in char_attribs_rows:
            current_data.setdefault(
                'attribs', {})[attrib_data.attrib_id] = attrib_data.value
        # Get the this character's item relation data
        char_items_rows = cls.execute_select("""
            SELECT *
            FROM char_items
            WHERE game_token = %s
                AND char_id = %s
        """, (g.game_token, id_to_get))
        for item_data in char_items_rows:
            current_data.setdefault('items', []).append(vars(item_data))
        # Mark this location as visited if it hasn't been yet
        if hasattr(current_data, 'location_id') and current_data.location_id:
            cls.execute_change(f"""
                UPDATE locations
                SET masked = false
                WHERE id = %s AND masked = true
            """, (current_data.location_id,))
        # Create object from data
        return Character.from_json(current_data)

    @classmethod
    def load_complete_objects(cls):
        """Load objects with everything needed for storing to JSON file."""
        logger.debug("load_complete_objects()")
        # Get char and progress data
        tables_rows = cls.select_tables("""
            SELECT *
            FROM {tables[0]}
            LEFT JOIN {tables[1]}
                ON {tables[1]}.id = {tables[0]}.progress_id
                AND {tables[1]}.game_token = {tables[0]}.game_token
            WHERE {tables[0]}.game_token = %s
        """, [g.game_token], ['characters', 'progress'])
        instances = {}  # keyed by ID
        for char_data, progress_data in tables_rows:
            instance = instances.setdefault(
                char_data.id, cls.from_json(char_data))
            if progress_data.id:
                instance.progress = Progress.from_json(progress_data, instance)
        # Get char attrib data
        attrib_rows = cls.execute_select("""
            SELECT *
            FROM char_attribs
            WHERE game_token = %s
        """, [g.game_token])
        for row in attrib_rows:
            instance = instances[row.char_id]
            instance.attribs[row.attrib_id] = AttribOf.from_json(row)
        # Get char item data
        item_rows = cls.execute_select("""
            SELECT *
            FROM char_items
            WHERE game_token = %s
        """, [g.game_token])
        for row in item_rows:
            instance = instances[row.char_id]
            instance.items[row.item_id] = OwnedItem.from_json(row, instance)
        # Print debugging info
        logger.debug("found %d characters", len(instances))
        logger.debug('\n'.join(
            f"character {instance.id} ({instance.name}) has"
            f" {len(instance.attribs)} attribs"
            for instance in instances.values()))
        # Set list of objects
        g.game_data.set_list(cls, list(instances.values()))
        return g.game_data.get_list(cls)

    @classmethod
    def data_for_configure(cls, id_to_get):
        logger.debug("data_for_configure(%s)", id_to_get)
        g.game_data.from_db_flat([Attrib, Location, Item])
        current_obj = cls.load_complete_object(id_to_get)
        # Replace partial objects with fully populated objects
        for attrib_id, attrib_of in current_obj.attribs.items():
            attrib_of.attrib = Attrib.get_by_id(attrib_id)
        for item_id, owned_item in current_obj.items.items():
            owned_item.item = Item.get_by_id(item_id)
        # Print debugging info
        logger.debug("found %d owned items", len(current_obj.items))
        if len(current_obj.items):
            owned_item = next(iter(current_obj.items.values()))
            logger.debug("item_id=%d, name=%s, quantity=%.1f, slot=%s",
                owned_item.item.id, owned_item.item.name, owned_item.quantity,
                owned_item.slot)
        return current_obj

    @classmethod
    def data_for_play(cls, id_to_get):
        logger.debug("data_for_play()")
        current_obj = cls.data_for_configure(id_to_get)
        if current_obj.location:
            # Get the current location's destination data
            tables_rows = cls.select_tables("""
                SELECT *
                FROM {tables[0]}
                INNER JOIN {tables[1]}
                    ON {tables[1]}.id = {tables[0]}.dest_id
                    AND {tables[1]}.game_token = {tables[0]}.game_token
                WHERE {tables[0]}.game_token = %s
                    AND {tables[0]}.loc_id = %s
            """, [g.game_token, current_obj.location.id],
                ['loc_destinations', 'locations'])
            for dest_data, loc_data in tables_rows:
                current_obj.location.destinations[loc_data.id] = Destination(
                    Location.from_json(loc_data),
                    dest_data.distance)
            # Travel distance
            if current_obj.destination:
                dest = current_obj.location.destinations.get(
                    current_obj.destination.id, None)
                if dest:
                    current_obj.pile.item.q_limit = dest.distance
        return current_obj

    def configure_by_form(self):
        req = RequestHelper('form')
        if req.has_key('save_changes'):  # button was clicked
            req.debug()
            self.name = req.get_str('char_name')
            self.description = req.get_str('char_description')
            req = RequestHelper('form')
            self.toplevel = req.get_bool('top_level')
            self.masked = req.get_bool('masked')
            item_ids = req.get_list('item_id[]')
            item_qtys = req.get_list('item_qty[]')
            item_slots = req.get_list('item_slot[]')
            self.items = {}
            for item_id, item_qty, item_slot in zip(
                    item_ids, item_qtys, item_slots):
                ownedItem = OwnedItem(Item(int(item_id)), self)
                self.items[item_id] = ownedItem
                ownedItem.quantity = float(item_qty)
                ownedItem.slot = item_slot
            location_id = req.get_int('char_location')
            self.location = Location(location_id) if location_id else None
            self.position = tuple(
                map(int, req.get_str('position').split(',')))
            attrib_ids = req.get_list('attrib_id[]')
            logger.debug(f"Attrib IDs: %s", attrib_ids)
            self.attribs = {}
            for attrib_id in attrib_ids:
                attrib_val = req.get_float(f'attrib_{attrib_id}_val', 0.0)
                self.attribs[attrib_id] = AttribOf(
                    attrib_id=attrib_id, val=attrib_val)
            logger.debug("attribs: %s", {
                attrib_of.attrib.name: attrib_of.val
                for attrib_of in self.attribs.values()})
            self.to_db()
        elif req.has_key('delete_character'):
            try:
                self.remove_from_db()
                session['file_message'] = 'Removed character.'
            except DbError as e:
                raise DeletionError(e)
        elif req.has_key('cancel_changes'):
            logger.debug("Cancelling changes.")
        else:
            logger.debug("Neither button was clicked.")
