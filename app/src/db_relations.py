"""
Relation tables must be created after base tables because
the keys depend on their prior existence.
"""
from .db_serializable import coldef

tables_to_create = {
    # Item
    'item_attribs': f"""
        {coldef('game_token')},
        item_id integer not null,
        attrib_id integer not null,
        value float(4) not null,
        PRIMARY KEY (game_token, item_id, attrib_id),
        FOREIGN KEY (game_token, item_id)
            REFERENCES items (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred,
        FOREIGN KEY (game_token, attrib_id)
            REFERENCES attribs (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred
        """,
    'recipe_sources': f"""
        {coldef('game_token')},
        recipe_id integer not null,
        item_id integer not null,
        q_required float(4) not null,
        preserve boolean not null,
        PRIMARY KEY (game_token, recipe_id, item_id),
        FOREIGN KEY (game_token, recipe_id)
            REFERENCES recipes (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred,
        FOREIGN KEY (game_token, item_id)
            REFERENCES items (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred
        """,
    'recipe_byproducts': f"""
        {coldef('game_token')},
        recipe_id integer not null,
        item_id integer not null,
        rate_amount float(4) not null,
        PRIMARY KEY (game_token, recipe_id, item_id),
        FOREIGN KEY (game_token, recipe_id)
            REFERENCES recipes (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred,
        FOREIGN KEY (game_token, item_id)
            REFERENCES items (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred
        """,
    'recipe_attribs': f"""
        {coldef('game_token')},
        recipe_id integer not null,
        attrib_id integer not null,
        value float(4) not null,
        PRIMARY KEY (game_token, recipe_id, attrib_id),
        FOREIGN KEY (game_token, recipe_id)
            REFERENCES recipes (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred,
        FOREIGN KEY (game_token, attrib_id)
            REFERENCES attribs (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred
        """,
    # Character
    'char_attribs': f"""
        {coldef('game_token')},
        char_id integer not null,
        attrib_id integer not null,
        value float(4) not null,
        PRIMARY KEY (game_token, char_id, attrib_id),
        FOREIGN KEY (game_token, char_id)
            REFERENCES characters (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred,
        FOREIGN KEY (game_token, attrib_id)
            REFERENCES attribs (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred
        """,
    'char_items': f"""
        {coldef('game_token')},
        char_id integer not null,
        item_id integer not null,
        quantity float(4) not null,
        slot varchar(50),
        PRIMARY KEY (game_token, char_id, item_id),
        FOREIGN KEY (game_token, char_id)
            REFERENCES characters (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred,
        FOREIGN KEY (game_token, item_id)
            REFERENCES items (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred
        """,
    # Location
    'loc_destinations': f"""
        {coldef('game_token')},
        loc1_id integer not null,
        loc2_id integer not null,
        distance float(4) not null,
        door1 integer[2],
        door2 integer[2],
        bidirectional boolean not null,
        PRIMARY KEY (game_token, loc1_id, loc2_id),
        FOREIGN KEY (game_token, loc1_id)
            REFERENCES locations (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred,
        FOREIGN KEY (game_token, loc2_id)
            REFERENCES locations (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred
        """,
    'loc_items': f"""
        {coldef('game_token')},
        loc_id integer not null,
        item_id integer not null,
        quantity float(4) not null,
        position integer[2],
        PRIMARY KEY (game_token, loc_id, item_id),
        FOREIGN KEY (game_token, loc_id)
            REFERENCES locations (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred,
        FOREIGN KEY (game_token, item_id)
            REFERENCES items (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred
        """,
    # Event
    'event_entities': f"""
        {coldef('game_token')},
        event_id integer not null,
        attrib_id integer,
        char_id integer,
        item_id integer,
        loc_id integer,
        reltype varchar(20) CHECK (reltype IN ('determining', 'changed', 'triggers')),
        UNIQUE (game_token, event_id, attrib_id, char_id, item_id, loc_id, reltype),
        FOREIGN KEY (game_token, event_id)
            REFERENCES events (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred,
        FOREIGN KEY (game_token, attrib_id)
            REFERENCES attribs (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred,
        FOREIGN KEY (game_token, char_id)
            REFERENCES characters (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred,
        FOREIGN KEY (game_token, item_id)
            REFERENCES items (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred,
        FOREIGN KEY (game_token, loc_id)
            REFERENCES locations (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred
        """,
    # Overall
    'win_requirements': f"""
        {coldef('id')},
        item_id integer,
        quantity float(4),
        char_id integer,
        loc_id integer,
        attrib_id integer,
        attrib_value float(4),
        UNIQUE (game_token, item_id, char_id, loc_id, attrib_id),
        FOREIGN KEY (game_token, item_id)
            REFERENCES items (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred,
        FOREIGN KEY (game_token, char_id)
            REFERENCES characters (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred,
        FOREIGN KEY (game_token, loc_id)
            REFERENCES locations (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred,
        FOREIGN KEY (game_token, attrib_id)
            REFERENCES attribs (game_token, id)
            ON DELETE cascade
            DEFERRABLE initially deferred
        """,
    }
