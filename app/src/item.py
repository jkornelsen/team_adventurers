from flask import g, request, session
import math

from .attrib import Attrib
from .db_serializable import (
    DbSerializable, Identifiable, MutableNamespace, coldef,
    DbError, DeletionError)
from .progress import Progress
from .utils import Storage, request_bool, request_float

tables_to_create = {
    'items': f"""
        {coldef('id')},
        {coldef('name')},
        {coldef('description')},
        {coldef('toplevel')},
        storage_type varchar(20) not null,
        q_limit float(4) NOT NULL,
        quantity float(4) NOT NULL,
        progress_id integer,
        FOREIGN KEY (game_token, progress_id)
            REFERENCES progress (game_token, id)
    """,
}

class Source:
    def __init__(self, new_id=0):
        self.item = Item(new_id)  # source item, not result item
        self.pile = self.item
        self.preserve = False  # if true then source will not be consumed
        self.q_required = 1.0

    def to_json(self):
        return {
            'source_id': self.item.id,
            'preserve': self.preserve,
            'q_required': self.q_required}

    @classmethod
    def from_json(cls, data):
        instance = cls()
        instance.item = Item(int(data.get('source_id', 0)))
        instance.preserve = data.get('preserve', False)
        instance.q_required = data.get('q_required', 1.0)
        return instance

class Recipe(DbSerializable):
    def __init__(self, new_id=0, item=None):
        self.id = int(new_id)  # only unique for a particular item
        self.item_produced = item
        self.rate_amount = 1.0  # quantity produced per batch
        self.rate_duration = 3.0  # seconds for a batch
        self.instant = False
        self.sources = []  # Source objects
        self.attribs = []  # elements are tuple (attrib_id, val)

    def to_json(self):
        return {
            'recipe_id': self.id,
            'item_id': self.item_produced.id if self.item_produced else 0,
            'rate_amount': self.rate_amount,
            'rate_duration': self.rate_duration,
            'instant': self.instant,
            'sources': [
                source.to_json()
                for source in self.sources],
            'attribs': self.attribs}

    @classmethod
    def from_json(cls, data, item_produced=None):
        instance = cls()
        instance.id = data.get('recipe_id', 0)
        instance.item_produced = (
            item_produced if item_produced
            else Item(int(data.get('item_id', 0))))
        instance.rate_amount = data.get('rate_amount', 1.0)
        instance.rate_duration = data.get('rate_duration', 3.0)
        instance.instant = data.get('instant', False)
        instance.sources = [
            Source.from_json(src_data)
            for src_data in data.get('sources', [])]
        instance.attribs = data.get('attribs', [])
        return instance

    def json_to_db(self, doc):
        print(f"{self.__class__.__name__}({self.id}).json_to_db()")
        self.insert_single(
            "recipes",
            "game_token, item_id, recipe_id,"
            " rate_amount, rate_duration, instant", (
                g.game_token, doc['item_id'], self.id,
                doc['rate_amount'],
                doc['rate_duration'],
                doc['instant']
                ))
        if doc['sources']:
            print(f"sources: {doc['sources']}")
            values = []
            for source in doc['sources']:
                values.append((
                    g.game_token, doc['item_id'], self.id,
                    source['source_id'],
                    source['q_required'],
                    source['preserve']
                    ))
            self.insert_multiple(
                "recipe_sources",
                "game_token, item_id, recipe_id,"
                " source_id, q_required, preserve",
                values)
        if doc['attribs']:
            print(f"attribs: {doc['attribs']}")
            attrib_values = []
            for attrib_id, attrib_value in doc['attribs']:
                attrib_values.append((
                    g.game_token, doc['item_id'], self.id,
                    attrib_id,
                    attrib_value
                ))
            self.insert_multiple(
                "recipe_attribs",
                "game_token, item_id, recipe_id,"
                " attrib_id, value",
                attrib_values
            )

class Item(Identifiable):
    PILE_TYPE = Storage.UNIVERSAL
    def __init__(self, new_id=""):
        super().__init__(new_id)
        self.name = ""
        self.description = ""
        self.storage_type = Storage.UNIVERSAL
        self.toplevel = False if len(self.get_list()) > 1 else True
        self.attribs = {}  # Attrib objects and their stat val
        self.recipes = []  # list of Recipe objects
        self.q_limit = 0.0  # limit the quantity if not 0
        self.quantity = 0.0  # general storage -- not owned or at location
        self.pile = self
        self.pile.item = self
        self.container = None  # general storage so not contained
        self.progress = Progress(container=self)  # for general storage

    def to_json(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'storage_type': self.storage_type,
            'toplevel': self.toplevel,
            'recipes': [
                recipe.to_json()
                for recipe in self.recipes],
            'attribs': {
                attrib.id: val
                for attrib, val in self.attribs.items()},
            'q_limit': self.q_limit,
            'quantity': self.quantity,
            'progress': self.progress.to_json(),
        }

    @classmethod
    def from_json(cls, data):
        if not isinstance(data, dict):
            data = vars(data)
        instance = cls(int(data.get('id', 0)))
        instance.name = data.get('name', "")
        instance.description = data.get('description', "")
        instance.storage_type = data.get('storage_type', Storage.UNIVERSAL)
        instance.toplevel = data.get('toplevel', False)
        instance.attribs = {
            Attrib(int(attrib_id)): val
            for attrib_id, val in data.get('attribs', {}).items()}
        instance.q_limit = data.get('q_limit', 0.0)
        instance.quantity = data.get('quantity', 0.0)
        instance.progress = Progress.from_json(
            data.get('progress', {}), instance)
        instance.recipes = [
            Recipe.from_json(recipe_data, instance)
            for recipe_data in data.get('recipes', [])]
        return instance

    def json_to_db(self, doc):
        print(f"{self.__class__.__name__}({self.id}).json_to_db()")
        self.progress.json_to_db(doc['progress'])
        doc['progress_id'] = self.progress.id
        super().json_to_db(doc)
        # Delete from recipe_sources for recipes of this item_id
        self.execute_change(f"""
            DELETE FROM recipe_sources
            USING recipe_sources AS rs
            LEFT OUTER JOIN recipes ON
                recipes.game_token = rs.game_token
                AND recipes.item_id = rs.item_id
                AND recipes.recipe_id = rs.recipe_id
            WHERE recipe_sources.game_token = rs.game_token
                AND recipe_sources.item_id = rs.item_id
                AND recipe_sources.recipe_id = rs.recipe_id
                AND recipe_sources.source_id = rs.source_id
                AND recipes.item_id = %s
                AND recipes.game_token = %s
        """, [self.id, self.game_token])
        # Delete from recipe_attribs for recipes of this item_id
        self.execute_change(f"""
            DELETE FROM recipe_attribs
            USING recipe_attribs AS ra
            LEFT OUTER JOIN recipes ON
                recipes.game_token = ra.game_token
                AND recipes.item_id = ra.item_id
                AND recipes.recipe_id = ra.recipe_id
            WHERE recipe_attribs.game_token = ra.game_token
                AND recipe_attribs.item_id = ra.item_id
                AND recipe_attribs.recipe_id = ra.recipe_id
                AND recipe_attribs.attrib_id = ra.attrib_id
                AND recipes.item_id = %s
                AND recipes.game_token = %s
        """, [self.id, self.game_token])
        for rel_table in ('item_attribs', 'recipes'):
            self.execute_change(f"""
                DELETE FROM {rel_table}
                WHERE item_id = %s AND game_token = %s
            """, (self.id, self.game_token))
        if doc['attribs']:
            values = [
                (g.game_token, self.id, attrib_id, val)
                for attrib_id, val in doc['attribs'].items()]
            self.insert_multiple(
                "item_attribs",
                "game_token, item_id, attrib_id, value",
                values)
        for recipe_data in doc.get('recipes', []):
            Recipe.from_json(recipe_data, self).to_db()

    @classmethod
    def db_item_and_progress_data(cls, item_id_for_progress=None):
        query = """
            SELECT *
            FROM {tables[0]}
            LEFT JOIN {tables[1]}
                ON {tables[1]}.id = {tables[0]}.progress_id
                AND {tables[1]}.game_token = {tables[0]}.game_token
        """
        values = []
        if item_id_for_progress:
            query += "AND {tables[0]}.id = %s\n"
            values.append(item_id_for_progress);
        values.append(g.game_token);
        query += """WHERE {tables[0]}.game_token = %s
            ORDER BY {tables[0]}.name
            """
        return cls.select_tables(
            query, values, ['items', 'progress'])

    @classmethod
    def db_attrib_data(cls, id_to_get=None, include_all=False):
        if id_to_get == 0:
            return []
        query = """
            SELECT *
            FROM {tables[0]}
            LEFT JOIN {tables[1]}
                ON {tables[1]}.game_token = {tables[0]}.game_token
                AND {tables[1]}.attrib_id = {tables[0]}.id
        """
        values = [g.game_token]
        if id_to_get:
            query += "AND {tables[1]}.item_id = %s\n"
            values = [id_to_get] + values
        query += "WHERE {tables[0]}.game_token = %s\n"
        if include_all:
            query += "ORDER BY {tables[0]}.name\n"
        else:
            query += "AND {tables[1]}.item_id IS NOT NULL\n"
        return cls.select_tables(
            query, values, ['attribs', 'item_attribs'])

    @classmethod
    def db_recipe_data(cls, id_to_get=None, get_by_source=False):
        if id_to_get == 0:
            return {}
        query = """
            SELECT *
            FROM {tables[0]}
            LEFT JOIN {tables[1]}
                ON {tables[1]}.game_token = {tables[0]}.game_token
                AND {tables[1]}.item_id = {tables[0]}.item_id
                AND {tables[1]}.recipe_id = {tables[0]}.recipe_id
        """
        item_conditions = [
            "WHERE {tables[0]}.game_token = %s"]
        values = [g.game_token]
        if id_to_get:
            if get_by_source:
                item_conditions.insert(0, "AND {tables[1]}.source_id = %s")
                values.insert(0, id_to_get);
            else:
                item_conditions.append("AND {tables[0]}.item_id = %s")
                values.append(id_to_get);
        query += "\n".join(item_conditions)
        sources_data = cls.select_tables(
            query, values, ['recipes', 'recipe_sources'])
        item_recipes_data = {}
        for row_recipe, row_recipe_source in sources_data:
            recipes_data = item_recipes_data.setdefault(row_recipe.item_id, {})
            recipe_data = recipes_data.setdefault(
                row_recipe.recipe_id, row_recipe)
            if row_recipe_source.source_id:
                recipe_data.setdefault('sources', []).append(row_recipe_source)
        attribs_data = []
        if get_by_source:
            return item_recipes_data
        query = """
            SELECT *
            FROM {tables[0]}
            LEFT JOIN {tables[1]}
                ON {tables[1]}.game_token = {tables[0]}.game_token
                AND {tables[1]}.item_id = {tables[0]}.item_id
                AND {tables[1]}.recipe_id = {tables[0]}.recipe_id
        """
        item_conditions = [
            "WHERE {tables[0]}.game_token = %s"]
        values = [g.game_token]
        if id_to_get is not None:
            item_conditions.append("AND {tables[0]}.item_id = %s")
            values.append(id_to_get);
        query += "\n".join(item_conditions)
        attribs_data = cls.select_tables(
            query, values, ['recipes', 'recipe_attribs'])
        for row_recipe, row_recipe_attrib in attribs_data:
            recipes_data = item_recipes_data.setdefault(
                row_recipe.item_id, {})
            recipe_data = recipes_data.setdefault(
                row_recipe.recipe_id, row_recipe)
            if row_recipe_attrib.attrib_id:
                recipe_data.setdefault('attribs', []).append(row_recipe_attrib)
        return item_recipes_data

    #@classmethod
    #def db_piles_for_sources_data(cls, current_obj, owner_char_id, at_loc_id):
    #    """Get piles at this loc or char that can be used for sources"""
    #    id_to_get = current_obj.id
    #    if id_to_get == 0:
    #        return {}
    #    # For carried sources select a char at this loc who owns one
    #    query = """
    #        SELECT *
    #        FROM {tables[0]}
    #        INNER JOIN {tables[1]}
    #            ON {tables[1]}.game_token = {tables[0]}.game_token
    #            AND {tables[1]}.item_id = {tables[0]}.source_id
    #            AND {tables[1]}.storage_type = 'carried'
    #        INNER JOIN {tables[2]}
    #            ON {tables[2]}.game_token = {tables[0]}.game_token
    #            AND {tables[2]}.location_id = %s
    #        INNER JOIN {tables[3]}
    #            ON {tables[3]}.game_token = {tables[0]}.game_token
    #            AND {tables[3]}.char_id = {tables[2]}.id
    #            AND {tables[3]}.item_id = {tables[0]}.source_id
    #            AND {tables[3]}.quantity > 0
    #        WHERE {tables[0]}.game_token = %s
    #            AND {tables[0]}.item_id = %s
    #    """
    #    piles_data = cls.select_tables(
    #        query, [at_loc_id, g.game_token, id_to_get],
    #        ['recipe_sources', 'items', 'characters', 'char_items'])
    #    piles = {}  # keys are source item id
    #    from .character import Character, OwnedItem
    #    for row_recipe_source, row_item, row_char, row_char_item in piles_data:
    #        pile = OwnedItem()
    #        pile.quantity = row_char_item.quantity
    #        pile.container = Character(row_char.id)
    #        piles[row_recipe_source.source_id] = pile
    #    # for local sources select an itemAt for this loc
    #    # for universal sources use the item in general storage
    #    # also find entities that meet attrib reqs

    @classmethod
    def load_piles_for_sources_data(cls, current_obj, owner_char_id, at_loc_id):
        """Get piles at this loc or char that can be used for sources.
        To do this, load all chars and items at this location
        by calling methods similar to Location.load_characters_at_loc().
        Then find piles for each source of this item using python loops.
        """
        #TODO
        # For carried sources select a char at this loc who owns one
        # for local sources select an itemAt for this loc
        # for universal sources use the item in general storage
        # also find entities that meet attrib reqs

    @classmethod
    def data_for_file(cls):
        print(f"{cls.__name__}.data_for_file()")
        # Get item and progress data
        tables_rows = cls.db_item_and_progress_data()
        instances = {}  # keyed by ID
        for item_data, progress_data in tables_rows:
            instance = instances.setdefault(
                item_data.id, cls.from_json(vars(item_data)))
            if progress_data.id:
                instance.progress = Progress.from_json(progress_data, instance)
        # Get attrib data for items
        tables_rows = cls.db_attrib_data()
        for attrib_data, item_attrib_data in tables_rows:
            instance = instances[item_attrib_data.item_id]
            attrib_obj = Attrib(attrib_data.id)
            instance.attribs[attrib_obj] = item_attrib_data.value
        # Get source data for items
        item_recipes_data = cls.db_recipe_data()
        for item_id, recipes_data in item_recipes_data.items():
            instance = instances[item_id]
            instance.recipes = [
                Recipe.from_json(recipe_data, instance)
                for recipe_data in recipes_data.values()]
            # Get the recipe that is currently in progress
            recipe_id = instance.progress.recipe.id
            if recipe_id:
                instance.progress.recipe = next(
                    (recipe for recipe in instance.recipes
                     if recipe.id == recipe_id), Recipe(item=instance))
        # Print debugging info
        print(f"found {len(instances)} items")
        for instance in instances.values():
            print(f"item {instance.id} ({instance.name})"
                f" has {len(instance.recipes)} recipes")
            if len(instance.recipes):
                recipe = instance.recipes[0]
                print(f"recipe id {recipe.id}")
                print(f"    rate_amount={recipe.rate_amount},"
                    f" rate_duration={recipe.rate_duration},"
                    f" instant={recipe.instant}")
                for source in recipe.sources:
                    print(f"    source item id {source.item.id},"
                        f" qty {source.q_required}")
        return list(instances.values())

    @classmethod
    def data_for_configure(cls, id_to_get):
        print(f"{cls.__name__}.data_for_configure()")
        if id_to_get == 'new':
            id_to_get = 0
        else:
            id_to_get = int(id_to_get)
        # Get all item data and the current item's progress data
        tables_rows = cls.db_item_and_progress_data(id_to_get)
        g.game_data.items = []
        current_data = MutableNamespace()
        for item_data, progress_data in tables_rows:
            if item_data.id == id_to_get:
                current_data = item_data
            if progress_data.id:
                item_data.progress = progress_data
            g.game_data.items.append(Item.from_json(item_data))
        # Get all attrib data and the current item's attrib relation data
        tables_rows = cls.db_attrib_data(id_to_get, include_all=True)
        for attrib_data, item_attrib_data in tables_rows:
            if item_attrib_data.attrib_id:
                current_data.setdefault(
                    'attribs', {})[attrib_data.id] = item_attrib_data.value
            g.game_data.attribs.append(Attrib.from_json(attrib_data))
        # Get the current item's source relation data
        item_recipes_data = cls.db_recipe_data(id_to_get)
        if item_recipes_data:
            recipes_data = list(item_recipes_data.values())[0]
            current_data.recipes = list(recipes_data.values())
        # Create item from data
        current_obj = Item.from_json(current_data)
        # Replace partial objects with fully populated objects
        populated_objs = {}
        for partial_attrib, val in current_obj.attribs.items():
            attrib = Attrib.get_by_id(partial_attrib.id)
            populated_objs[attrib] = val
        current_obj.attribs = populated_objs
        for recipe in current_obj.recipes:
            for source in recipe.sources:
                source.item = Item.get_by_id(source.item.id)
                source.pile = source.item
        # Print debugging info
        print(f"found {len(current_obj.recipes)} recipes")
        if len(current_obj.recipes):
            recipe = current_obj.recipes[0]
            print(f"recipe {recipe.id}"
                f" rate_amount={recipe.rate_amount}"
                f" instant={recipe.instant}")
            for source in recipe.sources:
                print(f"source item id {source.item.id} name {source.item.name}"
                    f" qty {source.q_required}")
        return current_obj

    @classmethod
    def data_for_play(cls, id_to_get, owner_char_id=0, at_loc_id=0,
            produced=False):
        print(f"{cls.__name__}.data_for_play()")
        current_obj = cls.data_for_configure(id_to_get)
        # Get all character and location names
        from .game_data import GameData
        from .character import Character
        from .location import Location
        GameData.entity_names_from_db([Character, Location])
        # Get item data for the specific container
        if produced:
            # Use the pile that will get produced
            pile_type = current_obj.storage_type
        elif current_obj.storage_type == Storage.CARRIED and owner_char_id:
            pile_type = Storage.CARRIED
        elif current_obj.storage_type == Storage.LOCAL and at_loc_id:
            pile_type = Storage.LOCAL
        elif owner_char_id:
            pile_type = Storage.CARRIED
        elif at_loc_id:
            pile_type = Storage.LOCAL
        else:
            pile_type = Storage.UNIVERSAL
        container = current_obj
        pile = current_obj
        if pile_type == Storage.CARRIED and owner_char_id:
            from .character import OwnedItem
            container = Character.data_for_configure(owner_char_id)
            pile = next(
                (ownedItem for ownedItem in container.items
                if ownedItem.item.id == current_obj.id),
                OwnedItem(current_obj))
        elif pile_type == Storage.LOCAL and at_loc_id:
            from .location import ItemAt
            container = Location.data_for_configure(at_loc_id)
            pile = next(
                (itemAt for itemAt in container.items
                if itemAt.item.id == current_obj.id),
                ItemAt(current_obj))
            Location.load_characters_at_loc(at_loc_id)  # who can pick up
        # Get piles at this loc or char that can be used for sources
        #db_piles_for_sources_data(current_obj, owner_char_id, at_loc_id)
        load_piles_for_sources_data(current_obj, owner_char_id, at_loc_id)
        # Get relation data for items that use this item as a source
        item_recipes_data = cls.db_recipe_data(id_to_get, get_by_source=True)
        for item_id, recipes_data in item_recipes_data.items():
            print(f"item_id {item_id}, recipes_data {recipes_data}")
            item = Item.get_by_id(item_id)
            item.recipes = [
                Recipe.from_json(recipe_data, item)
                for recipe_id, recipe_data in recipes_data.items()]
        return current_obj, pile, container

    def configure_by_form(self):
        if 'save_changes' in request.form:  # button was clicked
            print("Saving changes.")
            print(request.form)
            self.name = request.form.get('item_name')
            self.description = request.form.get('item_description')
            self.storage_type = request.form.get('storage_type')
            self.toplevel = request_bool(request, 'top_level')
            self.q_limit = request_float(request, 'item_limit')
            self.quantity = request_float(request, 'item_quantity')
            #if self.progress.is_ongoing:
            #    self.progress.stop()
            recipe_ids = request.form.getlist('recipe_id')
            self.recipes = []
            for recipe_id in recipe_ids:
                recipe = Recipe(int(recipe_id), self)
                self.recipes.append(recipe)
                recipe.rate_amount = request_float(request,
                    f'recipe{recipe_id}_rate_amount')
                recipe.rate_duration = request_float(request,
                    f'recipe{recipe_id}_rate_duration')
                recipe.instant = request_bool(request,
                    f'recipe{recipe_id}_instant')
                source_ids = request.form.getlist(
                    f'recipe{recipe_id}_source_id')
                print(f"Source IDs: {source_ids}")
                for source_id in source_ids:
                    source = Source.from_json({
                        'source_id': int(source_id),
                        'q_required': request_float(request,
                            f'recipe{recipe_id}_source{source_id}_qtyreq',
                            0.0),
                        'preserve': request_bool(request,
                            f'recipe{recipe_id}_source{source_id}_preserve'),
                    })
                    recipe.sources.append(source)
                    print(f"Sources for {recipe_id}: ",
                        {source.item.id: source.q_required
                        for source in recipe.sources})
                recipe_attrib_ids = request.form.getlist(
                    f'recipe{recipe_id}_attrib_id')
                for attrib_id in recipe_attrib_ids:
                    attrib_value = request_float(request,
                        f'recipe{recipe_id}_attrib{attrib_id}_value', 1.0)
                    recipe.attribs.append((attrib_id, attrib_value))
            attrib_ids = request.form.getlist('attrib_id')
            print(f"Attrib IDs: {attrib_ids}")
            self.attribs = {}
            for attrib_id in attrib_ids:
                attrib_val = request_float(request,
                    f'attrib{attrib_id}_val', 0.0)
                attrib_obj = Attrib(attrib_id)
                self.attribs[attrib_obj] = attrib_val
            print("attribs: ", {attrib.id: val
                for attrib, val in self.attribs.items()})
            self.to_db()
        elif 'delete_item' in request.form:
            try:
                self.remove_from_db()
                session['file_message'] = 'Removed item.'
            except DbError as e:
                raise DeletionError(e)
        elif 'cancel_changes' in request.form:
            print("Cancelling changes.")
        else:
            print("Neither button was clicked.")
