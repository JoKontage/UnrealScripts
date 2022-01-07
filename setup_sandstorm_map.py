# Unreal Python script
# Attempts to fix various issues in Source engine Datasmith
# imports into Unreal
from collections import Counter, defaultdict, OrderedDict

import unreal
import re
import traceback
import os
import json
import csv
import posixpath
import math
from glob import glob

# This is the SCALE / 100 which we set in HammUEr when importing models.
# Source maps are bigger than Sandstorm for whatever reason --
# so we've had to scale things down a bit.
# We *need* this scale to be accurate or the placement of
# objects will be *waaaaay* off if we go by the Origin in
# our imported notes. When spawning an item at the Origin defined
# by an imported note (IE: for nbot_cover notes), we need to
# divide each value (Y, X, Z) by this HAMMUER_SCALE
#
# FYI, the ridiculous number below was found by dividing the location
# specified in a Note actor (IE: 319.99) to the same HammUEr-translated
# point value (IE: 736.116821) in that same object.
# ( *sigh* I hate floats... )
HAMMUER_SCALE = 0.4347000243321434

# REQUIRED! We use the values found in the map.txt files for
# placement of objectives, spawns, ...
GCFSCAPE_EXPORT_DIRECTORY = r"C:\Modding\Source\scripts\exports\doi"
BSPSRC_EXPORT_DIRECTORY = r"C:\Modding\Source\scripts\decompiled_maps"

# Regex for VMF parsing
PLANE_SPLIT_RE = re.compile(r'\((.+?)\)')
ARRAY_RE = re.compile(r'([-0-9.]+)')
THREE_NUM_STR_RE = re.compile(r'^[-0-9.]+ [-0-9.]+ [-0-9.]+$')

# A set of actor labels to use for ensuring we
# don't place the same actor multiple times
PLACED_ACTORS = set()

# Shortcuts for creating material node connections
CREATE_EXPRESSION = unreal.MaterialEditingLibrary.create_material_expression
CREATE_CONNECTION = unreal.MaterialEditingLibrary.connect_material_expressions
CONNECT_PROPERTY = unreal.MaterialEditingLibrary.connect_material_property
CONNECT_EXPRESSIONS = unreal.MaterialEditingLibrary.connect_material_expressions

# Use to create material node connections
CHILD_OBJECT_REGEX = re.compile(r".*_\d{3}$")


def isnumeric(value):
    try:
        float(value)
        return True
    except:
        return False


def num_to_alpha(num):
    """ Convert a number > 0 and < 24 into it's Alphabetic equivalent """
    num = int(num)  # Ensure num is an int
    if num < 0:
        raise ValueError("wtf? num_to_alpha doesn't like numbers less than 0...")
    if num > 24:
        raise ValueError("seriously? there's no way you have more than 24 objectives...")
    return chr(65 + num)


def get_world_mod_name(world=None):
    if not world:
        world = unreal.EditorLevelLibrary.get_editor_world()
    # <0:nothing>/<2:mod_name>/...
    mod_name = world.get_path_name().split('/')[1]
    return mod_name


def parse_key_value_pair(string):
    if string and string[0] == '"' and string[-1] == '"':
        items = string[1:-1].split("\" \"")
        if len(items) == 1:
            items = re.split(r"\"(\s+)\"", items[0])
        if len(items) == 2:
            if items[0] == "plane":
                items[0] = "planes"
                match = PLANE_SPLIT_RE.findall(items[1])
                items[1] = []
                for tup_str in match:
                    items[1].append(
                        get_source_engine_origin([float(x) for x in tup_str.split()])
                    )
            elif items[0] == "origin":
                items[1] = get_source_engine_origin([float(x) for x in items[1].split()])
            elif len(items[1]) > 2 and items[1][0] == "[" and items[1][-1] == "]":
                items[1] = [float(x) for x in ARRAY_RE.findall(items[1])]
            elif isnumeric(items[1]):
                try:
                    items[1] = int(items[1])
                except:
                    items[1] = float(items[1])
            elif THREE_NUM_STR_RE.match(items[1]):
                items[1] = [float(x) for x in items[1].split()]

            # Fix team numbers for Sandstorm
            if items[0] == "TeamNum":
                items[1] = items[1] - 2

        return tuple(items)


def parse_entry(parent, section):
    entries = {}

    indent = 0
    current_section_name = None
    for index, line in enumerate(section):
        if line == '{':
            if indent == 0:
                current_section_name = section[index - 1]
                # Replace key names
                for replacement in [
                    ("camera", "cameras"), ("entity", "entities"),
                    ("solid", "solids"), ("side", "sides"), ("plane", "planes"),
                ]:
                    if current_section_name == replacement[0]:
                        current_section_name = replacement[1]
                start = index + 1
            indent += 1
        elif line == '}':
            indent -= 1
            if indent == 0:
                stop = index
                if current_section_name in entries.keys():
                    entries[current_section_name].append((start, stop))
                else:
                    entries.setdefault(current_section_name, [(start, stop)])
        else:
            if index < len(section)-1:
                if section[index + 1] == '{':
                    pass
                elif indent == 0:
                    pair = parse_key_value_pair(line)
                    if pair:
                        if len(pair) == 1:
                            print("WTF?! %s" % str(pair))
                        else:
                            parent.setdefault(pair[0], pair[1])
            else:
                if indent == 0:
                    pair = parse_key_value_pair(line)
                    if pair:
                        if len(pair) == 1:
                            print("WTF?! %s" % str(pair))
                        else:
                            parent.setdefault(pair[0], pair[1])

    for entry in entries:
        if len(entries[entry]) > 1:
            parent.setdefault(entry, [])
            for part in entries[entry]:
                sub_dict = {}
                parse_entry(sub_dict, section[part[0]:part[1]])
                parent[entry].append(sub_dict)
        elif len(entries[entry]) == 1:
            parent.setdefault(entry, {})
            parse_entry(parent[entry], section[entries[entry][0][0]:entries[entry][0][1]])


def convert_vmf_to_dict(filepath):
    vmf = []
    with open(filepath, "r") as vmf_file:
        for line in vmf_file:
            vmf.append(line.strip().strip('\n'))
    parent = {}
    parse_entry(parent, vmf)
    return parent


def convert_vmf_to_json(filepath, is_pretty=False):
    import json
    vmf_dict = convert_vmf_to_dict(filepath)
    if is_pretty:
        return json.dumps(vmf_dict, sort_keys=True, indent=4, separators=(',', ': '))
    else:
        return json.dumps(vmf_dict)


def convert_vmf_to_json_export(filepath_in, filepath_out, is_pretty=False):
    jvmf = convert_vmf_to_json(filepath_in, is_pretty)
    text_file = open(filepath_out, "w")
    text_file.write(jvmf)
    text_file.close()


def get_snake_case(text):
    # If world_name contains CamelCase lettering, add an _
    # before each uppercase letter following the first letter
    # TODO: This is a stupid way to do this, right? *Maybe* fix it .. but ... it *does* work ...
    text = "".join(reversed([c if c.islower() else "_%s" % c for c in reversed(text)]))

    # If world_name has a leading underscore, remove it
    text = text[1:] if text[0] == "_" else text

    # Ensure world_name is lowercase
    return text.lower()


def get_vmf_data_for_current_map(world_name, debug_output_path=None):

    world_name = get_snake_case(world_name)

    # Find level's "maps" script
    search_query = os.path.join(BSPSRC_EXPORT_DIRECTORY, r"%s_d.vmf" % world_name.lower())
    print("[*] Searching for VMF with query: %s" % search_query)
    map_file_path = list(glob(search_query))
    if map_file_path:
        if debug_output_path:
            convert_vmf_to_json_export(map_file_path[0], debug_output_path, True)
            # os.system("explorer %s" % debug_output_path)
        return convert_vmf_to_dict(map_file_path[0])
    raise ValueError("no VMF map found with search query: %s" % search_query)


def cast(object_to_cast=None, object_class=None):
    """
    # object_to_cast: obj unreal.Object : The object you want to cast
    # object_class: obj unreal.Class : The class you want to cast the object into
    """
    try:
        return object_class.cast(object_to_cast)
    except Exception:
        return None


def get_all_properties(unreal_class=None):
    """
    # Note: Also work using the command : help(unreal.StaticMesh)
    # unreal_class: obj : The class you want to know the properties
    # return: str List : The available properties (formatted the way you can directly use them to get their values)
    """
    return unreal.CppLib.get_all_properties(unreal_class)


def get_all_actors(use_selection=False, actor_class=None, actor_tag=None, world=None):
    """
    # use_selection: bool : True if you want to get only the selected actors
    # actor_class: class unreal.Actor : The class used to filter the actors. Can be None if you do not want to use this filter
    # actor_tag: str : The tag used to filter the actors. Can be None if you do not want to use this filter
    # world: obj unreal.World : The world you want to get the actors from. If None, will get the actors from the currently open world.
    # return: obj List unreal.Actor : The actors
    """
    world = world if world is not None else unreal.EditorLevelLibrary.get_editor_world() # Make sure to have a valid world
    if use_selection:
        selected_actors = get_selected_actors()
        class_actors = selected_actors
        if actor_class:
            class_actors = [x for x in selected_actors if cast(x, actor_class)]
        tag_actors = class_actors
        if actor_tag:
            tag_actors = [x for x in selected_actors if x.actor_has_tag(actor_tag)]
        return [x for x in tag_actors]
    elif actor_class:
        actors = unreal.GameplayStatics.get_all_actors_of_class(world, actor_class)
        tag_actors = actors
        if actor_tag:
            tag_actors = [x for x in actors if x.actor_has_tag(actor_tag)]
        return [x for x in tag_actors]
    elif actor_tag:
        tag_actors = unreal.GameplayStatics.get_all_actors_with_tag(world, actor_tag)
        return [x for x in tag_actors]
    else:
        actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
        return [x for x in actors]


def hide_all_actors_with_material_name(material_name):
    """ Hide all actors with the specified material (with Undo support) """
    matching_actors = list()

    with unreal.ScopedEditorTransaction("Hiding Actors (in-game) with Specific Mat") as trans:
        
        # Find all actors with the specified material and add them
        # to the "matching_actors" list.
        for actor in get_all_actors(actor_class=unreal.StaticMeshActor):

            if actor_contains_material(actor, material_name):
                print(" - hiding actor: %s" % actor.get_name())

                # Hide this specified actor in-game
                actor.set_actor_hidden_in_game(True)

                # Turn off collision
                actor.set_actor_enable_collision(False)

                # Add this actor to our "matching_actors" list
                matching_actors.append(actor)

    return matching_actors


def move_actors_to_folder(actors, folder_name):
    for actor in actors:
        if not actor:
            continue
        try:
            actor.set_folder_path(folder_name)
        except Exception as ex:
            print(ex)


def spawn_blueprint_actor(asset_path='', label=None, actor_location=None, actor_rotation=None,
                          local_rotation=None, actor_scale=None, properties={}, hidden=False):
    """
    # path: str : Blueprint class path
    # actor_location: obj unreal.Vector : The actor location
    # actor_rotation: obj unreal.Rotator : The actor rotation
    # actor_location: obj unreal.Vector : The actor scale
    # world: obj unreal.World : The world in which you want to spawn the actor. If None, will spawn in the currently open world.
    # properties: dict : The properties you want to set before the actor is spawned. These properties will be taken into account in the Construction Script
    # return: obj unreal.Actor : The spawned actor
    """
    if actor_location:
        actor_location = actor_location if isinstance(actor_location, unreal.Vector) else unreal.Vector(*actor_location)
    if actor_rotation:
        actor_rotation = actor_rotation if isinstance(actor_rotation, unreal.Rotator) else unreal.Rotator(*actor_rotation)

    # Attempt to find the specified Blueprint class
    actor_class = unreal.EditorAssetLibrary.load_blueprint_class(asset_path)

    # Spawn the blueprint class!
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        actor_class, location=actor_location, rotation=actor_rotation)
    if not actor:
        print("[!] Failed to spawn actor: %s" % label)
        return None

    # If "actor_rotation" is actuall a Vector and not a Rotator,
    # we'll assume the caller wanted to add local rotation
    if local_rotation:
        actor.add_actor_local_rotation(local_rotation, sweep=False, teleport=True)
    if actor_scale:
        actor.set_actor_scale3d(actor_scale)
    if label:
        actor.set_actor_label(label)
    if hidden:
        actor.set_actor_hidden_in_game(hidden)

    # Edit Properties
    for x in properties:
        actor.set_editor_property(x, properties[x])

    return actor


def select_actors(actors_to_select=[]):
    """
    # Note: Will always clear the selection before selecting.
    # actors_to_select: obj List unreal.Actor : The actors to select.
    """
    unreal.EditorLevelLibrary.set_selected_level_actors(actors_to_select)


def get_selected_actors():
    """ return: obj List unreal.Actor : The selected actors in the world """
    return unreal.EditorLevelLibrary.get_selected_level_actors()


def generate_entity_spreadsheets(open_directory=False):
    entities = dict()
    for actor in get_all_actors(actor_class=unreal.Note):
        if not actor:
            continue
        note = get_note_actor_details(actor)
        if note and "classname" in note:
            if not note["classname"] in entities:
                entities[note["classname"]] = list()
            entities[note["classname"]].append(note)

    if not entities:
        print("[!] No entities parsed!")
    else:
        # Get the name of this world
        persistent_world = unreal.EditorLevelLibrary.get_editor_world()
        root_level_name = persistent_world.get_name()

        csv_dir = "C:\\Modding\\Source\\Spreadsheets"
        if not os.path.exists(csv_dir):
            os.makedirs(csv_dir)
        for entity_type, entity_list in entities.items():
            entity_fieldnames = {key: True for x in entity_list for key in x.keys()}.keys()
            csv_path = os.path.join(csv_dir, "%s - %s.csv" % (root_level_name, entity_type))
            if entity_list:
                with open(csv_path, "wb") as f:
                    writer = csv.DictWriter(f, fieldnames=entity_fieldnames)
                    writer.writeheader()
                    writer.writerows(entity_list)

        # Open the directory containing all spreadsheets
        if open_directory:
            os.system("explorer %s" % csv_dir)


def get_sky_camera(actors_to_search=None):
    # Find the sky_camera actor
    actors_to_search = actors_to_search if actors_to_search else get_all_actors(actor_class=unreal.Note)
    for actor in actors_to_search:
        # Skip null ObjectInstance actors
        # (which trigger: Exception: WorldSettings: Internal Error - ObjectInstance is null!)
        if not actor:
            continue
        if actor.get_actor_label().startswith("sky_camera"):
            return actor
    return None


def get_skybox_actors(sky_camera_actor=None, max_distance_to_skybox=6000,
                      actors_to_search=None, remove_if_found=False,
                      select_actors=False):
    """ Return all actors within N distance to the sky_camera """
    skybox_actors = dict()

    # Find the sky_camera actor
    actors_to_search = actors_to_search if actors_to_search else get_all_actors()
    if not sky_camera_actor:
        sky_camera_actor = get_sky_camera(actors_to_search)
    sky_camera_location = sky_camera_actor.get_actor_location()

    # Find the real distance between the sky_camera actor and the location
    # of each actor's bounding box (it's *true* location)
    for actor in actors_to_search:

        # Skip null ObjectInstance actors
        # (which trigger: Exception: WorldSettings: Internal Error - ObjectInstance is null!)
        if not actor:
            continue

        # If this actor isn't in PersistentLevel, skip it
        # as it's already in a sublevel (and normally wouldn't be
        # unless we put it there on purpose)
        try:
            actor_level = actor.get_outer()
        except:
            # We couldn't get this actor's "outer" -- skip it!
            continue

        actor_level_name = actor_level.get_name()
        if actor_level_name != "PersistentLevel":
            continue

        actor_distance_to_sky_camera = actor.get_actor_bounds(False)[0].distance(sky_camera_location)
        if actor_distance_to_sky_camera < max_distance_to_skybox:

            # Add this actor to our skybox-specific actors dictionary,
            # where the key is it's label
            skybox_actors[actor.get_actor_label()] = actor

            # Select this actor
            if select_actors:
                unreal.EditorLevelLibrary.set_actor_selection_state(actor, should_be_selected=True)

    return skybox_actors


def get_note_actor_details(actor):
    """ Parse values and information from imported unreal.Note actor text """

    note = dict()
    for line in actor.text.splitlines():

        # Skip blank lines
        if not line:
            continue

        # Split this line by spaces
        line_split = line.split(" = ")
        if not line_split:
            continue

        # Retrieve the first word -- the "key"
        key = line_split[0]
        value_split = line_split[1].split()
        if len(value_split) == 1:

            # There's only one value to parse
            try:
                # Attempt to parse this as a number (float)
                note[key] = float(value_split[0])
            except Exception:
                # Add the value as a string, since it failed
                # to be converted to a number
                note[key] = value_split[0]

        else:
            # Since this key has multiple values,
            # make it a list
            note[key] = list()

            # There are multiple values to parse!
            for val in value_split:
                try:
                    # Attempt to parse this as a number (float)
                    note[key].append(float(val))
                except Exception:
                    # Add the value as a string, since it failed
                    # to be converted to a number
                    note[key].append(val)

    return note


def get_source_engine_world_rotation(yzx_list):
    # Source Engine *adds* degrees when you move counter-clockwise
    # Source Engine's "0-point" is ->
    # Our "0-point" is ^
    # Since we *subtract* degrees when we rotate counter-clockwise and
    # our "0-point" is ^, we need to subtract source's angle by an offset of 90
    # to get the proper rotation:
    if isinstance(yzx_list, unicode):
        yzx_list = yzx_list.encode("utf8", "ignore")
    if isinstance(yzx_list, str):
        # Convert this str to a list
        yzx_list = [float(n) for n in filter(lambda v: v, re.split(r"\s+", yzx_list))]
        if not yzx_list or len(yzx_list) < 3:
            raise ValueError("couldn't translate source_origin_list: %s" % yzx_list)
    return [yzx_list[2], yzx_list[0], 90 - yzx_list[1]]


def get_source_engine_origin(source_origin_list):
    """ Return the correct world position given a Source engine Origin list [Y, X, Z] """
    if isinstance(source_origin_list, unicode):
        source_origin_list = source_origin_list.encode("utf8", "ignore")
    if isinstance(source_origin_list, str):
        # Convert this str to a list
        source_origin_list = [float(n) for n in filter(lambda v: v, re.split(r"\s+", source_origin_list))]
        if not source_origin_list or len(source_origin_list) < 3:
            raise ValueError("couldn't translate source_origin_list: %s" % source_origin_list)
    return [
        source_origin_list[1] / HAMMUER_SCALE,
        source_origin_list[0] / HAMMUER_SCALE,
        source_origin_list[2] / HAMMUER_SCALE]


def get_json_values_for_current_map(world=None):
    """ Attempt to find this level's map .txt file """
    if not world:
        world = unreal.EditorLevelLibrary.get_editor_world()

    world_name = get_snake_case(world.get_name())

    # Find level's "maps" script
    search_query = os.path.join(GCFSCAPE_EXPORT_DIRECTORY, r"**\%s.txt" % world_name)
    map_file_path = list(glob(search_query))
    if map_file_path:
        print("[*] Attempting to parse map: %s" % map_file_path[0])
        return convert_txt_format_to_json(open(map_file_path[0], "r").read())

    # We couldn't retrieve the map text -- so return nothing
    raise ValueError("couldn't find map file '%s.txt' in GCFSCAPE_EXPORT_DIRECTORY: %s" % (
        world_name, GCFSCAPE_EXPORT_DIRECTORY))


def actor_contains_named_mesh(actor, mesh_name):
    if isinstance(actor, unreal.StaticMeshActor):

        static_mesh_component = actor.get_component_by_class(unreal.StaticMeshComponent)
        if not static_mesh_component:
            return False

        # Skip if there's no static mesh to display
        if not static_mesh_component.static_mesh:
            return False

        # Check if this static mesh is named whatever we
        # specified in our mesh_name variable
        return static_mesh_component.static_mesh.get_name() == mesh_name

    return False


def actor_contains_material_starting_with(actor, material_name):
    """ If this actor is StaticMeshActor and contains a material with
        a name beginning with any of the words in the provided material_name,
        return True -- else return False
    """
    if not material_name:
        return False
    if isinstance(actor, unreal.StaticMeshActor):

        static_mesh_component = actor.get_component_by_class(unreal.StaticMeshComponent)
        if not static_mesh_component:
            return False

        # Skip if there's no static mesh to display
        if not static_mesh_component.static_mesh:
            return False

        # Check if the static mesh has materials -- which we'll fix if applicable
        mats = static_mesh_component.get_materials()
        if not mats:
            return False

        # Iterate through all materials found in this static mesh
        for mat in mats:

            if not mat:
                continue

            # Check if the name of the current material starts with "tools"
            mat_name = mat.get_name()
            if not mat_name:
                continue

            if mat_name.startswith(material_name):
                return True

    # Actor wasn't a StaticMesh or no materials matched
    return False


def actor_contains_material(actor, material_name, containing=True):
    """ If this actor is StaticMeshActor and contains a material with
        a name beginning with any of the words in the provided words_tuple,
        return True -- else return False
    """
    if not material_name:
        return False
    if isinstance(actor, unreal.StaticMeshActor):

        static_mesh_component = actor.get_component_by_class(unreal.StaticMeshComponent)

        # Skip if there's no static mesh to display
        if not static_mesh_component.static_mesh:
            return False

        # Check if the static mesh has materials -- which we'll fix if applicable
        mats = static_mesh_component.get_materials()
        if not mats:
            return False

        # Iterate through all materials found in this static mesh
        for mat in mats:

            if not mat:
                continue

            # Check if the name of the current material starts with "tools"
            mat_name = mat.get_name()
            if not mat_name:
                continue

            if mat_name.startswith(material_name) or (containing and material_name in mat_name):
                return True

    # Actor wasn't a StaticMesh -- so we couldn't be sure
    # it was a tool. Skip this actor ...
    return False


def actor_contains_material_containing(actor, material_name, all_mats_must_match=True):
    """ If this actor is StaticMeshActor and contains a material with
        a name beginning with any of the words in the provided material_name,
        return True -- else return False
    """
    all_mats_matched = True
    if isinstance(actor, unreal.StaticMeshActor):

        static_mesh_component = actor.get_component_by_class(unreal.StaticMeshComponent)

        # Skip if there's no static mesh to display
        if not static_mesh_component.static_mesh:
            return False

        # Check if the static mesh has materials -- which we'll fix if applicable
        mats = static_mesh_component.get_materials()
        if not mats:
            return False

        # Iterate through all materials found in this static mesh
        for mat in mats:

            # Some materials may not be present
            # in the materials array -- skip if so
            if not mat:
                all_mats_matched = False
                continue

            # Check if the name of the current material starts with "tools"
            mat_name = mat.get_name()
            if not mat_name:
                return False

            if material_name in mat_name:

                if not all_mats_must_match:
                    # We don't require all materials match -- only 1
                    # Return True because at least 1 material name matched
                    # our provided words
                    return True

            else:
                # This material name didn't start with the words
                # we provided. If we require all material names
                # to begin with at least 1 of the words provided,
                # return False
                if all_mats_must_match:
                    return False

        # Return True because all material names matched our provided words
        return all_mats_matched

    # Actor wasn't a StaticMesh -- so we couldn't be sure
    # it was a tool. Skip this actor ...
    return False


def raycast_reposition_on_hit(actor, world, direction=None, ignore_classes=[], ignore_with_mats=None, height=0, width=0.35):
    """ Ensure our actor isn't overlapping with anything in the specified direction
        and reposition it if it is. height: 0 == feet, height: 1 == head
    """
    if not direction:
        return False, 0
    if not ignore_with_mats:
        ignore_with_mats = ("tools")

    actor_bounds = actor.get_actor_bounds(only_colliding_components=False)
    actor_location = actor.get_actor_location()
    raycast_location = actor_location.copy()
    raycast_location.z += actor_bounds[1].z * (1.7 * 0.001 + height)

    if direction == "forward" or direction == "backwards":
        # 1 == forward, -1 == back
        direction = 1 if direction == "forward" else -1

        # Position the raycast slightly above our actor's "feet"
        raycast_distance = actor_bounds[1].x * width * 1.2  # 1.2 added to increase this forward/backwards ray slightly
        position_slightly_in_front_of_actor = raycast_location + (
                (actor.get_actor_forward_vector() * direction) * raycast_distance)

        # Cast the ray and check for a hit!
        hit_results = unreal.SystemLibrary.line_trace_multi(
            world,
            start=raycast_location, end=position_slightly_in_front_of_actor,
            trace_channel=unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
            trace_complex=True, actors_to_ignore=[], draw_debug_type=unreal.DrawDebugTrace.FOR_DURATION,
            ignore_self=True)
        if hit_results:
            for hit_result in hit_results:
                hit_result_info = hit_result.to_tuple()

                # Skip doing anything if this actor is a type we should ignore
                if hit_result_info[9].get_class() in ignore_classes:
                    print("%s == %s" % (hit_result_info[9].get_name(), hit_result_info[9].get_class()))
                    continue

                if actor_contains_material_starting_with(hit_result_info[9], ignore_with_mats):
                    continue

                # We hit something we're not ignoring! Position us out of it's bounds
                actor.set_actor_location(actor_location - (
                        (actor.get_actor_forward_vector() * direction) * 40),
                                         sweep=False, teleport=True)

                # We're done now -- let our caller know we hit something facing this direction
                # and the distance to that object
                return True, hit_result_info[3]

    elif direction == "right" or direction == "left":
        # 1 == right, -1 == left
        direction = 1 if direction == "left" else -1

        raycast_distance = actor_bounds[1].y * width
        position_slightly_to_the_right_of_actor = raycast_location + (
                (actor.get_actor_right_vector() * direction) * raycast_distance)

        # Cast the ray and check for a hit!
        hit_results = unreal.SystemLibrary.line_trace_multi(
            world,
            start=raycast_location, end=position_slightly_to_the_right_of_actor,
            trace_channel=unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
            trace_complex=True, actors_to_ignore=[], draw_debug_type=unreal.DrawDebugTrace.FOR_DURATION,
            ignore_self=True)
        if hit_results:
            for hit_result in hit_results:
                hit_result_info = hit_result.to_tuple()

                # Skip doing anything if this actor is a type we should ignore
                if hit_result_info[9].get_class() in ignore_classes:
                    continue

                if actor_contains_material_starting_with(hit_result_info[9], ignore_with_mats):
                    continue

                # We hit something we're not ignoring! Position us out of it's bounds
                actor.set_actor_location(actor_location - ((actor.get_actor_right_vector() * direction) * 20),
                                         sweep=False, teleport=True)
                # We're done now -- let our caller know we hit something facing this direction
                # and the distance to that object
                return True, hit_result_info[3]

    elif direction == "down" or direction == "up":
        # TODO: Ignore 'ignore_classes'
        # We'll place this actor at the location it hits on the ground
        # 1 == right, -1 == left
        direction = 1 if direction == "up" else -1

        middle_of_body_z = actor_location.z + (actor_bounds[1].z)

        #if direction == -1:
        #    # We want to start from the "head" of the actor
        #    # if we're sending a raycast down
        #    raycast_distance = actor_bounds[1].z * 4
        #else:
        raycast_distance = actor_bounds[1].z * 3

        position_slightly_below_actor = raycast_location + (
                (actor.get_actor_up_vector() * direction) * raycast_distance)

        # Cast the ray and check for a hit!
        hit_results = unreal.SystemLibrary.line_trace_multi(
            world,
            start=raycast_location, end=position_slightly_below_actor,
            trace_channel=unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
            trace_complex=True, actors_to_ignore=[], draw_debug_type=unreal.DrawDebugTrace.FOR_DURATION,
            ignore_self=True)
        if hit_results:
            for hit_result in hit_results:
                # 0. blocking_hit=False,
                # 1. initial_overlap=False,
                # 2. time=0.0
                # 3. distance=0.0,
                # 4. location=[0.0, 0.0, 0.0],
                # 5. impact_point=[0.0, 0.0, 0.0],
                # 6. normal=[0.0, 0.0, 0.0],
                # 7. impact_normal=[0.0, 0.0, 0.0],
                # 8. phys_mat=None,
                # 9. hit_actor=None,
                # 10. hit_component=None,
                # 11. hit_bone_name='None',
                # 12. hit_item=0,
                # 13. face_index=0,
                # 14. trace_start=[0.0, 0.0, 0.0],
                # 15. trace_end=[0.0, 0.0, 0.0]
                # VIEW INFO: print(hit_result.to_tuple())
                hit_result_info = hit_result.to_tuple()
                if actor_contains_material_starting_with(hit_result_info[9], ignore_with_mats):
                    continue

                if direction == 1:

                    # We hit something above us!
                    # Let our caller know this happened and the distance
                    # from our feet to the object above us
                    return True, hit_result_info[3]

                else:

                    # We hit something below us. Place us *right* above it
                    hit_result_location = hit_result_info[5]

                    # We were trying to check for the ground, but
                    # it's *above* the middle of our body?
                    # Nahhh - this must be the ceiling.
                    # Move onto the next hit
                    if hit_result_location.z > middle_of_body_z:
                        continue

                    # print("[*] AC LOC: %d, NEW LOC: %d" % (actor_location.z, hit_result_location.z))

                    # Place slightly above the hit location
                    hit_result_location.z += 30
                    actor.set_actor_location(hit_result_location, sweep=False, teleport=True)

                    # Let the caller know we hit something below us.
                    # Return True and the distance between our head and the ground
                    return True, hit_result_info[3]

    elif direction == "diags":

        # Cast raycasts in all four relative diagonal directions of the actor
        raycast_location.z -= 50
        for diagdir in [(1,1), (1,-1), (-1,1), (-1,-1)]:

            raycast_location_copy = raycast_location.copy()
            raycast_distance = actor_bounds[1].y * width
            real_diag_dir = (actor.get_actor_forward_vector() * diagdir[0]) + (actor.get_actor_right_vector() * diagdir[1])
            diag_position = raycast_location_copy + (real_diag_dir * raycast_distance)

            # Cast the ray and check for a hit!
            hit_results = unreal.SystemLibrary.line_trace_multi(
                world,
                start=raycast_location_copy, end=diag_position,
                trace_channel=unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
                trace_complex=True, actors_to_ignore=[], draw_debug_type=unreal.DrawDebugTrace.FOR_DURATION,
                ignore_self=True)
            if hit_results:
                for hit_result in hit_results:
                    hit_result_info = hit_result.to_tuple()

                    # Skip doing anything if this actor is a type we should ignore
                    if hit_result_info[9].get_class() in ignore_classes:
                        continue

                    if actor_contains_material_starting_with(hit_result_info[9], ignore_with_mats):
                        print("HIT DIAG BUT IGNORED MAT")
                        continue

                    # We hit something we're not ignoring! Position us out of it's bounds
                    actor.set_actor_location(actor_location - (real_diag_dir * 15), sweep=False, teleport=True)

                    # We're done now -- let our caller know we hit something facing this direction
                    # and the distance to that object
                    return True, hit_result_info[3]


    # We didn't return above -- so we didn't hit anything
    return False, 0


def convert_txt_format_to_json(mapfile_contents):
    """
    No - please! Stay away! tHiS cOdE iS hIdEoUs!!!
    I sWeAr -- I'm just too LaZy right now -- not inept!!!
    """
    for regex, sub in [
        # Remove the text at the start of the file
        (r'^".+"\n', r''),
        # Remove comments
        (r'//.*?\n', r'\n'),
        # Fix keys
        (r'"(\s+|\n\s+){', r'": {'),
        # Add commas to the end of each section
        (r'}(\n|\s+\n)', r'},\1'),
        # Remove commas from dict-ends
        (r'},(\s+?|\n\s+?)}', r'}\1}'),
        (r'},(\s+?|\n\s+?)}', r'}\1}'),
        # Remove commas from ending dict end
        (r'},\n$', r'}'),
        # Add colons between keys and values
        (r'"(.+?)"\s+"(.*?)"', r'"\1": "\2",'),
        # Turn strings containing digits only into numbers
        (r'"(\d+)"([^:])', r'\1\2'),
        # Remove blank links
        (r'\n+', r'\n'),
        # Turn string arrays into real arrays [Y, X, Z]
        (r'"([-0-9.]+) ([-0-9.]+) ([-0-9.]+)"', r'[\1, \2, \3]'),
        # Remove commas trailing the last property
        (r'("|\]|\d+),(\s+|\n\s+)}', r'\1\2}'),
    ]:
        mapfile_contents = re.sub(regex, sub, mapfile_contents)

    # Stupid way to remove any trailing commas
    mapfile_contents = mapfile_contents.rstrip()
    if mapfile_contents[-1] == ",":
        mapfile_contents = mapfile_contents[:-1]

    # Define a function to use in our json load below
    # that will append an iterating integer to the end
    # of each duplicate key
    def manage_duplicates(pairs):
        d = OrderedDict()
        k_counter = Counter(defaultdict(int))
        for k, v in pairs:
            # print("%s: %s" % (k, str(v)))
            if isinstance(v, dict):
                v = manage_duplicates(v.items())
            new_key = "%s_%d" % (k, k_counter[k]) if k_counter[k] > 0 else k
            d[new_key] = v
            k_counter[k] += 1
        return d

    # DEBUG: Take a look at the contents if json.loads fails to parse
    #"""
    with open("tmp.json", "wb") as f:
        f.write(mapfile_contents.encode("utf-8"))
    # os.system("explorer tmp.json")
    #"""

    # Turn the string of JSON into a dict
    json_data = json.loads(mapfile_contents, object_pairs_hook=manage_duplicates)

    # Make the ..["ai"]["objectives"] and ..["navspawns"]["navspawns"] into lists
    for _, root_dict in json_data.items():

        # Skip root key/value pairs that aren't dicts
        if not isinstance(root_dict, dict) or "TeamOne" not in root_dict:
            continue

        # Replace "AttackingTeam" (TEAM_TWO, TEAM_ONE) with actual numbers
        if "AttackingTeam" in root_dict:
            root_dict["AttackingTeam"] = 0 if root_dict["AttackingTeam"] == "TEAM_ONE" else 1

        # Replace "teamnumber" with the actual Sandstorm team numbers
        def fix_team_numbers(obj):
            if "teamnumber" in obj:
                obj["teamnumber"] = obj["teamnumber"] - 2
            for k, v in obj.items():
                if isinstance(v, dict):
                    fix_team_numbers(v)
        fix_team_numbers(root_dict)

        # Fix origin lists (from [Y, X, Z] to [X, Y, Z] with scaling)
        def fix_origins(obj):
            if "origin" in obj:
                obj["origin"] = get_source_engine_origin(obj["origin"])
            for k, v in obj.items():
                if isinstance(v, dict):
                    fix_origins(v)
        fix_origins(root_dict)

        # Fix navspawn locations
        def fix_navspawn_locations(obj):
            location_keys = list(filter(lambda k: k.startswith("location"), obj.keys()))
            if location_keys:
                for location_key in location_keys:
                    obj[location_key] = get_source_engine_origin(obj[location_key])
            for k, v in obj.items():
                if isinstance(v, dict):
                    fix_navspawn_locations(v)
        fix_navspawn_locations(root_dict)

        # Fix required objectives
        def fix_required_objectives(obj):
            if "required_objectives" in obj:
                if isinstance(obj["required_objectives"], int):
                    obj["required_objectives"] = [obj["required_objectives"]]
                else:
                    obj["required_objectives"] = [int(n) for n in filter(lambda v: v.strip(), obj["required_objectives"].split(","))]
            for k, v in obj.items():
                if isinstance(v, dict):
                    fix_required_objectives(v)
        fix_required_objectives(root_dict)

        # Fix angles (from [Y, Z, X] to [X, Y, Z] with offset)
        def fix_angles(obj):
            if "angles" in obj:
                obj["angles"] = get_source_engine_world_rotation(obj["angles"])
            for k, v in obj.items():
                if isinstance(v, dict):
                    fix_angles(v)
        fix_angles(root_dict)

        # Place all "controlpoint" key/value pairs into a single "controlpoints" list
        controlpoints = list()
        for sub_key, sub_dict in root_dict.items():
            if sub_key.startswith("controlpoint"):
                controlpoints.append(sub_dict)
                root_dict.pop(sub_key)
        root_dict["controlpoints"] = controlpoints

        # Place all "objectives" key/value pairs into a single "objectives" list
        if "ai" in root_dict:
            objectives = list()
            for sub_key, sub_dict in root_dict["ai"].items():
                if sub_key.startswith("objectives"):
                    objectives.append(sub_dict)
                    root_dict["ai"].pop(sub_key)
            root_dict["ai"]["objectives"] = objectives

        # Place all "objective_based_spawns" key/value pairs into a single list
        if "navspawns" in root_dict:
            objective_based_spawns = list()
            for sub_key, sub_dict in root_dict["navspawns"].items():
                if sub_key.startswith("objective_based_spawns"):
                    objective_based_spawns.append(sub_dict)
                    root_dict["navspawns"].pop(sub_key)
            root_dict["navspawns"]["objective_based_spawns"] = objective_based_spawns

    return json_data


def convert_note_to_nbot_cover(item, sublevels=None, fire_from_feet=True):
    """ Spawn a CoverActor where this note resides.
    Example Note Details:
    Deployable = 0
    ProtectionAngle = 135
    Ranking = 0
    TeamNum = 2
    angles = 0 85 0
    classname = nbot_cover
    id = 4707813
    origin = -1152 -1448 239.225
    """
    note_actor = item["actor"]
    note = item["note"]
    new_actor_label = "%s_inss" % note_actor.get_actor_label()

    # This AICoverActor was already placed during a previous
    # execution of this script! Skip it
    if new_actor_label in PLACED_ACTORS:
        return

    # NOTE: Origin is (Y, X, Z)
    # NOTE: angles is (Y, Z, X) -- Yes, it's weird. Thanks, Source.
    # NOTE: TeamNum - 2 is the *actual* team
    # NOTE: The directory the actor should face is -X
    # NOTE: "nbot_cover"'s are placed ~80 units above the ground
    # NOTE: We'll likely need to move the AICoverActor back a few units
    cover_actor_location = note_actor.get_actor_location()
    cover_actor_location.z -= 80
    cover_actor_rotation = unreal.Rotator(*get_source_engine_world_rotation(note["angles"]))

    # Spawn the new actor
    new_actor = spawn_blueprint_actor("/Game/Game/AI/Actors/AICoverActor",
                          label=new_actor_label,
                          actor_location=cover_actor_location,
                          actor_rotation=cover_actor_rotation,
                          actor_scale=note_actor.get_actor_scale3d(),
                          properties=dict())

    # Get the current world
    world_context_object = unreal.EditorLevelLibrary.get_editor_world()

    # Reposition to the ground, changing our stance if the ground
    # is *very* close to the position we were spawned in
    stance = unreal.SoldierStance.STAND
    hit_something_below, distance = raycast_reposition_on_hit(new_actor, world_context_object, "down")
    if hit_something_below:
        if distance < 220:
            stance = unreal.SoldierStance.CROUCH
        elif distance < 160:
            stance = unreal.SoldierStance.PRONE

    # Make sure our new AICoverActor isn't overlapping with any objects
    # by moving it out of the way of objects it overlaps with!
    for height in range(0, 10):
        height /= 10.0
        for dir in ["forward", "backwards", "right", "left", "diags"]:
            hit_something, distance = raycast_reposition_on_hit(new_actor, world_context_object, direction=dir, height=height)
            # if hit_something:
            #    print("hit!")

    raycast_reposition_on_hit(new_actor, world_context_object, direction="forward", width=1.1)
    raycast_reposition_on_hit(new_actor, world_context_object, direction="backwards", width=1.1)

    # If our AICoverActor is overlapping with something above it, make it crouch!
    hit_something_above, distance = raycast_reposition_on_hit(new_actor, world_context_object, "up")
    if hit_something_above:
        print("dist to hit above: %d" % distance)
        if distance < 270:
            stance = unreal.SoldierStance.CROUCH
        elif distance < 180:
            stance = unreal.SoldierStance.PRONE

    # new_actor is an AICoverActor, which has
    # a "Cover" component. The "Cover" component
    # can define the stance, protection angle, launcher priority (good rocket launcher position?),
    # scope priority (is this a good sniper position?), machine gunner priority,
    # "ambush node" (good ambush position?), and "rank" (how important it is to bots)
    cover_component = new_actor.get_component_by_class(unreal.CoverComponent)
    cover_component.set_editor_properties({
        "stance": stance,
        "protection_angle": note["ProtectionAngle"],
        "machine_gunner_priority": int(note["Deployable"]) if "Deployable" in note else 0,
        "rank": note["Ranking"] if "Ranking" in note else 200  # Save 300 for high-priority locations
    })

    # Add this new AICoverActor to our "actors" list,
    # to be sent to the "AI" sublevel
    if sublevels:
        sublevels["AI"]["actors"].append(new_actor)


def parse_note_actors(note_actors, sublevels):

    # Sort and store all valid notes
    for note_actor in note_actors:

        note_actor_label = note_actor.get_actor_label()
        note = get_note_actor_details(note_actor)

        # Note is valid and contains a class,
        # therefore run this entity's proper function
        note_classname = note["classname"] if "classname" in note else None
        if note_classname:

            # Make sure there's a dict created for this note type
            if not note_classname in sublevels["Notes"]:
                sublevels["Notes"][note_classname] = {}

            # Store this note as Notes -> [note type, ie: nbot_cover] -> [note_actor_label] -> {note, actor}
            sublevels["Notes"][note_classname][note_actor_label] = {
                "note": note, "actor": note_actor,
            }

    # Place all nbot_covers
    if "nbot_cover" in sublevels["Notes"]:
        for item in sublevels["Notes"]["nbot_cover"].values():
            convert_note_to_nbot_cover(item, sublevels)

    # HammUEr is trash for importing notes ... :(
    # We'll need to use our map_info and map_data to figure
    # out where to place everything but these nbot covers

    return False


def create_capture_zone(label, location):
    if label in PLACED_ACTORS:
        print("[!] Already placed ObjectiveCapturable: %s" % label)
        return None
    location = location if isinstance(location, unreal.Vector) else unreal.Vector(*location)
    cza = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.CaptureZone, location, unreal.Rotator(0, 0, 0))
    cza.set_actor_label(label)
    cza.set_actor_scale3d(unreal.Vector(8, 8, 6))  # TODO: Find a way to set the actual scale of DoI capture zones ...
    cza.set_editor_property("spawn_collision_handling_method", unreal.SpawnActorCollisionHandlingMethod.ALWAYS_SPAWN)
    return cza


def create_objective_capturable(label, location, rotation, capture_zones=None, cls=None,
                                print_name=None, objective_letter=None):
    if label in PLACED_ACTORS:
        print("[!] Already placed ObjectiveCapturable: %s" % label)
        return None
    if not cls:
        cls = unreal.ObjectiveCapturable
    location = location if isinstance(location, unreal.Vector) else unreal.Vector(*location)
    rotation = rotation if isinstance(rotation, unreal.Rotator) else unreal.Rotator(*rotation)
    oca = unreal.EditorLevelLibrary.spawn_actor_from_class(cls, location, rotation)
    oca.set_actor_label(label)
    if capture_zones:
        oca.set_editor_property("capture_zones", capture_zones)
    if print_name:
        oca.set_editor_property("print_name", print_name)
    if objective_letter:
        oca.set_editor_property("override_objective_letter", True)
        oca.set_editor_property("objective_letter", objective_letter)
    return oca


def create_objective_destructible(label, location, rotation, asset_path=None):
    if asset_path:
        oda = spawn_blueprint_actor(asset_path, label, location, rotation)
    else:
        oda = create_objective_capturable(label, location, rotation, cls=unreal.ObjectiveDestructible)
    return oda


def create_spawnzone(label, location, team_id):
    """ Create INSSpawnZone from label, location, and for the specified Team ID """
    if label in PLACED_ACTORS:
        print("[!] Already placed INSSpawnZone: %s" % label)
        return None
    location = location if isinstance(location, unreal.Vector) else unreal.Vector(*location)

    # Create the INSSpawnZone actor for this spawn using the spawn's locaiton
    sza = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.SpawnZone,
                                                           location=location,
                                                           rotation=unreal.Rotator(0, 0, 0))
    sza.set_actor_label(label)
    sza.set_editor_property("team_id", team_id)
    sza.set_actor_enable_collision(False)
    sza.set_actor_scale3d(unreal.Vector(8, 8, 6))  # Mostly guessing a decent scale here, lol
    return sza


def create_spawnzone_counterattack(label, location, team_id):
    """ Create INSSpawnZone from label, location, and for the specified Team ID """
    if label in PLACED_ACTORS:
        print("[!] Already placed INSSpawnZone: %s" % label)
        return None
    location = location if isinstance(location, unreal.Vector) else unreal.Vector(*location)

    # Create the INSSpawnZone actor for this spawn using the spawn's locaiton
    sza = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.SpawnZoneCounterAttack,
                                                           location=location,
                                                           rotation=unreal.Rotator(0, 0, 0))
    sza.set_actor_label(label)
    sza.set_editor_property("team_id", team_id)
    sza.set_actor_enable_collision(False)
    sza.set_actor_scale3d(unreal.Vector(1, 1, 1))  # Mostly guessing a decent scale here, lol
    return sza


def create_spawns_in_spawnzone(spawn_zone, rows=4, cols=4):
    """ Attempt to create evenly-spaced INSPlayerStart spawns in the specified SpawnZone """

    print("[*] Creating %d * %d (%d) spawns in spawn zone: %s" % (rows, cols, rows*cols, spawn_zone.get_name()))

    # Cast a ray from the top of the Spawnzone to the bottom and ... ?
    szl = spawn_zone.get_actor_location()
    team_id = spawn_zone.get_editor_property("team_id")
    padding = 150
    height_offset = 200

    spawns = list()
    for row in reversed(range(0, rows)):
        for col in reversed(range(0, cols)):
            
            # Attempt to set location in a grid-like, padded pattern
            location = unreal.Vector(szl.x - (row * padding / 2), szl.y - (col * padding / 2), szl.z + height_offset)
            sp = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.INSPlayerStart,
                                                                  location=location,
                                                                  rotation=unreal.Rotator(0, 0, 0))
            # TODO: Reposition spawn correctly using raycasts ... ?
            sp.set_editor_properties({
                "enabled": False,
                "team_specific": True,
                "team_id": team_id,
                "associated_spawn_zone": spawn_zone,
                "spawn_collision_handling_method": unreal.SpawnActorCollisionHandlingMethod.ALWAYS_SPAWN
            })

            # Add this spawn
            spawns.append(sp)

    print("[*] SPAWNED %d SPAWNS FOR SPAWN_ZONE: %s" % (len(spawns), spawn_zone.get_name()))

    # TODO: Maybe automate this portion? Not sure where to find the correct rotations ...
    print("[!] MAKE SURE TO MANUALLY ROTATE SPAWN POINTS!!!!")
    return spawns


def create_supply_crate(label, location, rotation):
    if label in PLACED_ACTORS:
        print("[!] Already placed BP_SupplyCrate_Base: %s" % label)
        return None
    scba = spawn_blueprint_actor("/Game/Game/Actors/World/BP_SupplyCrate_Base", label, location, rotation)
    scba.set_actor_label(label)
    return scba


def create_gamemode_actors(gamemode, map_info, map_data, sublevels):
    """
    Basically do everything we couldn't do with HammUEr-imported data by using
    info parsed from this map's .txt and .vmf files :)
    """

    """
    NOOOOOTEEEEEEEEEEEEEEEESSSSSSSSSSSSSSSS:

    - Misc TODOs from looking at Precinct:
        - doors should have a SoundscapeTriggerDoor which points in the direction from inside -> outside
        - has a "Front Soundscape" and "Back Soundscape"
        - for fire, steal from BP_FireBarrel
        - DISABLE (hide the sublevel) ALL GAMEMODES BY DEFAULT!!!!!
            - gamemmode sublevels should contain all the objects below (spawnzones, spawnpoints, objectives, ...)

    - trigger_capture_zone (unreal.CaptureZone)
        - Sandstorm name example: CZCheckpoint_A1
        - set:
            - "spawn_collision_handling_method" (unreal.SpawnActorCollisionHandlingMethod.ALWAYS_SPAWN)
        - scale normally to define the capturable area this CZ provides
        - there can be *multiple* per point! Having 8 for 1 point is common

    - point_controlpoint (unreal.ObjectiveCapturable)
        - Sandstorm name example: OCCheckpoint_A
        - set:
            - OPTIONAL: "print_name" (what shows in the HUD -- not normally used)
            - OPTIONAL: "override objective letter" (default False)
            - OPTIONAL: "objective_letter" (could be the name instead of a letter ... ?)
            - "capture_zones" (array of unreal.CaptureZone which define the capturable area)
        - there should only be one per point!
        - size/scale don't matter -- the size/scale of the "capture_zones" we define *DO*

    - ins_spawnzone (unreal.INSSpawnZone)
        - Sandstorm name example: SZCheckpointA
        - set:
            - "team_id"
        - should use: set_actor_enable_collision(False)
        - there don't appear to be SpawnZoneCounterAttack actors in DoI, but:
            - Sandstorm name example: SZCheckpointA1_Team2, SZCheckpointA2_Team2

    - ins_spawnpoint (unreal.INSPlayerStart)
        - Sandstorm name example: INSPlayerStart (default)
        - set:
            - "enabled" (False)
            - "team_specific" (True if checkpoint)
            - "team_id" (proper team ID: 0 or 1)
            - "associated_spawn_zone"
            - OPTIONAL: "soundscape_override" (set eventually)
            - "spawn_collision_handling_method" (unreal.SpawnActorCollisionHandlingMethod.ALWAYS_SPAWN)
        - links to a ins_spawnzone via "associated_spawn_zone"

    - obj_destructible, obj_weapon_cache, obj_destructible_vehicle, obj_fuel_dump (unreal.ObjectiveDestructible)
        - Sandstorm name example: ODCheckpoint_A
        - set:
            - OPTIONAL: "print_name" (default: Weapon Cache)
            - "bot_initial_spawn_method" (unreal.ObjectiveBotSpawnMethod.CLOSEST_TO_OBJECTIVE)

    - obj_ammo_crate (Blueprint: /Game/Game/Actors/World/BP_SupplyCrate_Base)
        - Sandstorm name example: BP_SupplyCrate_Base (default)
        - set:
            - "linked_spawn_zone"
            - "linked_objective" (AKA: the point_controlpoint)
            - OPTIONAL: "print_name" (default: Weapon Cache")
            - OPTIONAL: "resupply_timeout_time" (DoI is infinite?)
            - OPTIONAL: "allowed_times_to_be_used" (-1 for unlimited; default)
        - can change mesh!
        - can make breakable!
        - should set "bot_initial_spawn_method" to unreal.ObjectiveBotSpawnMethod.CLOSEST_TO_OBJECTIVE

    - objectives and their spawnzones are linked in the Scenario
    """

    # ------------------------------------ 0. Ensure this map has the Sandstorm-equivalent gamemode!
    gamemode_translations = {
        "Checkpoint": "stronghold",
        "Frontline": "frontline",
        "Outpost": "entrenchment",
    }
    translated_gamemode = None
    for gamemode_key, gamemode_translation in gamemode_translations.items():
        if gamemode.startswith(gamemode_key):
            translated_gamemode = gamemode_translation
            break
    if not translated_gamemode or translated_gamemode not in map_info:
        # Either we wanted to skip this gamemode by not providing the Sandstorm -> DoI translation
        # or this gamemode doesn't exist for this DoI map by default
        print("[!] Failed to find gamemode '%s' in gamemode translations" % gamemode)
        return False

    gamemode_info = map_info[translated_gamemode]

    # ------------------------------------ 1. Create SpawnZones and spawn points!
    sublevels[gamemode]["neutral_spawnzones"] = list()
    sublevels[gamemode]["objective_based_spawns"] = list()
    attacking_team = 0 if "Security" in gamemode else 1
    spawns_that_exist = dict()

    # COOP gamemodes have navspawns (all?)
    if "navspawns" in gamemode_info:

        for navspawn_type, spawn_zones in gamemode_info["navspawns"].items():

            # We'll skip spawns that aren't objective-based spawns.
            # This *should* be fine -- as long as this gamemode is coop :P
            if navspawn_type != "objective_based_spawns":
                continue

            # sz has "objective_index", "location_axis", "location_allies"
            print("[*] SPAWN_ZONES: {}".format(spawn_zones))
            for sz in spawn_zones:

                # We don't know the proper scale for spawn zones ...
                # Scale would normally be defined (I think) by the volumes
                # we would create using solid planes in map_data ... but ..
                # not sure how we'd link those back to spawn zone indexes
                # We'll be lazy here and use the same scale for each spawnzone
                # as the spawn point locations seem to matter more.
                objective_spawnzones = list()
                for team_id, spawn_label in enumerate(["location_allies", "location_axis"]):

                    # Ensure this team has a spawnzone for this index:
                    if not spawn_label in sz:
                        continue

                    # If this spawn zone belongs to the attacking team, spawn INSPlayerSpawns
                    if attacking_team == team_id:

                        # Create the INSSpawnZone actor for this spawn using the spawn's locaiton
                        spawn_name = "SZ%s%s_Team%d" % (translated_gamemode.capitalize(),
                                                        num_to_alpha(sz["objective_index"]), team_id + 1)

                        if spawn_name in spawns_that_exist:
                            print("[*] Already created spawn: %s" % spawn_name)
                            continue

                        print(" - attempting to create spawnzone: %s" % spawn_name)

                        sza = create_spawnzone(spawn_name, sz[spawn_label], team_id)
                        if sza:

                            # Attempt to create INSPlayerStarts (16) for this INSSpawnZone
                            spawns = create_spawns_in_spawnzone(sza, rows=4, cols=4)

                            # Add this INSSpawnZone to our list of spawnzones
                            objective_spawnzones.append(sza)
                            sublevels[gamemode]["actors"].append(sza)
                            for spawn in spawns:
                                sublevels[gamemode]["actors"].append(spawn)

                            # Ensure no dupes
                            spawns_that_exist[spawn_name] = True

                        else:
                            print("[!] FAILED TO CREATE SPAWNZONE: %s" % spawn_name)
                    
                    # This spawn zone doesn't belong to the attacking team; spawn SpawnZoneCounterAttack
                    # without spawns (as it doesn't need them)
                    else:

                        # Create the INSSpawnZone actor for this spawn using the spawn's locaiton
                        spawn_num = 1
                        spawn_name = "SZ%s%s_Team%d" % (
                            translated_gamemode.capitalize(),
                            num_to_alpha(sz["objective_index"]) + "{}".format(spawn_num),
                            team_id + 1)

                        if spawn_name in spawns_that_exist:
                            print("[*] Already created spawn: %s" % spawn_name)
                            continue

                        print(" - attempting to create spawnzone: %s" % spawn_name)

                        szca = create_spawnzone_counterattack(spawn_name, sz[spawn_label], team_id)
                        if szca:
                            # Add this INSSpawnZone to our list of spawnzones
                            objective_spawnzones.append(szca)
                            sublevels[gamemode]["actors"].append(szca)
                        else:
                            print("[!] FAILED TO CREATE SPAWNZONE COUNTERATTACK: %s" % spawn_name)

                # Append these spawns to our "objective_spawns" list (where each index contains all the spawns
                # for that objective -- IE: objective_spawns[0] contains a spawn for Allies (index 0)
                # and one for Axis (index 1)
                if objective_spawnzones:
                    sublevels[gamemode]["objective_based_spawns"].append(objective_spawnzones)

    # PVP Gamemode
    else:

        # TODO: Actually parse PVP/non-checkpoint spawnzones :P
        # PVP has these (more than one key, with keys "0", "1", etc...)
        if "spawnzones" in gamemode_info and len(gamemode_info["spawnzones"]) > 1:
            for spawnzone_index_str, spawnzone_name in gamemode_info["spawnzones"].items():

                # Find both Allied and Axis spawnzone volumes with this name in the level
                # If this is a attack/defense type gamemode, there could be multiple -- and
                # they'll be tied to some entity objective in "entities".
                # If this is firefight (pure PVP)

                # Parse our map_data to find the actual spawn data related to this spawnzone_name
                spawn_zones = list(filter(lambda e: "targetname" in e and e["targetname"] == spawnzone_name, map_data["entities"]))
                if spawn_zones:
                    # Create the spawns we found
                    if "entities" in map_info[translated_gamemode]:
                        # This is a gamemode with objectives! Tie these spawns with objectives
                        objective_spawns = list()
                        for sz in spawn_zones:
                            spawn_name = "SZ%s%s_Team%d" % (translated_gamemode.capitalize(),
                                                            num_to_alpha(spawnzone_index_str), sz["TeamNum"] + 1)
                            sza = create_spawnzone(spawn_name, sz["origin"], sz["TeamNum"])
                            if sza:
                                objective_spawns.append(sza)
                                sublevels[gamemode]["actors"].append(sza)
                        sublevels[gamemode]["objective_based_spawns"].append(objective_spawns)
                    else:
                        for sz in spawn_zones:
                            # This is a gamemode without objectives! Use neutral_spawnzones instead
                            spawn_name = "SZ%s_Team%d" % (translated_gamemode.capitalize(), sz["TeamNum"] + 1)
                            sza = create_spawnzone(spawn_name, sz["origin"], sz["TeamNum"])
                            if sza:
                                sublevels[gamemode]["neutral_spawnzones"].append(sza)
                                sublevels[gamemode]["actors"].append(sza)
                else:
                    print("[!] COULDN'T FIND SPAWN: %s" % spawnzone_name)

    # ------------------------------------ 2. Spawn any Objectives this gamemode specifies
    sublevels[gamemode]["objectives"] = list()
    if "controlpoints" in gamemode_info:

        for index, controlpoint_name in enumerate(gamemode_info["controlpoints"]):
            controlpoint_name = controlpoint_name.replace("_cap", "")
            controlpoint_items = list(
                filter(lambda e:
                       "targetname" in e and e["targetname"].startswith(controlpoint_name) or
                       "controlpoint" in e and e["controlpoint"].startswith(controlpoint_name),
                       map_data["entities"]))
            if controlpoint_items:

                # We'll replace this variable with the actual parsed Objective(Capturable/Destructible) below
                objective = None

                # Create this controlpoint's triggers
                controlpoint_cap_triggers = list(
                    filter(lambda t: t["classname"] == "trigger_capture_zone", controlpoint_items))
                if controlpoint_cap_triggers:

                    # Create this trigger
                    controlpoint_cap_trigger = controlpoint_cap_triggers[0]
                    controlpoint_cap_trigger_label = "CZ%s_%s" % (translated_gamemode.capitalize(), num_to_alpha(index))

                    # Check if this capture zone already exists and skip it's creation if so
                    capture_zone = unreal.EditorLevelLibrary.get_actor_reference("PersistentLevel.%s" % controlpoint_cap_trigger_label)
                    if not capture_zone:

                        # This capture zone likely doesn't exist -- create a new one
                        capture_zone = create_capture_zone(controlpoint_cap_trigger_label, controlpoint_cap_trigger["origin"])

                    if capture_zone:
                        print(" - Capturepoint Trigger created or found: %s" % controlpoint_cap_trigger_label)

                        # Add capture zone to actors
                        sublevels[gamemode]["actors"].append(capture_zone)

                    else:
                        print(" ! Capturepoint Trigger NOT created or found: %s" % controlpoint_cap_trigger_label)

                    # Find and create the actual capture point (ObjectiveCapturable)
                    controlpoint_caps = list(
                        filter(lambda t: t["classname"] == "point_controlpoint", controlpoint_items))
                    if controlpoint_caps:

                        controlpoint_cap = controlpoint_caps[0]
                        objective_capturable_label = "OC%s_%s" % (translated_gamemode.capitalize(), num_to_alpha(index))

                        # Check if this capture zone already exists and skip it's creation if so
                        objective = unreal.EditorLevelLibrary.get_actor_reference(
                            "PersistentLevel.%s" % objective_capturable_label)
                        if not objective:

                            # This objective likely doesn't exist -- create a new one
                            objective = create_objective_capturable(objective_capturable_label,
                                                                    controlpoint_cap["origin"],
                                                                    unreal.Rotator(0, 0, 0),
                                                                    capture_zones=[capture_zone])
                            
                            # Add objective capturable to actors list
                            sublevels[gamemode]["actors"].append(objective)

                        if objective:
                            print(" - Created objective for CP: %s" % controlpoint_name)
                        else:
                            print(" - Couldn't create objective for CP: %s" % controlpoint_name)

                    else:
                        print(" ! No controlpoint_caps found for: %s" % controlpoint_name)

            else:
                # This must be a destroyable objective?
                # We'll create an ObjectiveDestructible instead of ObjectiveCapturable

                # ControlPoint wasn't in map_data -- maybe it's in our gamemode_info "entities" list ... ?
                controlpoint_destructible_info = None
                for entity_key, entity in gamemode_info["entities"].items():
                    if "ControlPoint" in entity and entity["ControlPoint"] == controlpoint_name:
                        controlpoint_destructible_info = entity
                        break

                if not controlpoint_destructible_info:
                    print("[!] Missing controlpoint item for CP: %s" % controlpoint_name)
                    continue
                objective_destructible_label = "OD%s_%s" % (translated_gamemode.capitalize(), num_to_alpha(index))

                # Check if this objective already exists and skip it's creation if so
                objective = unreal.EditorLevelLibrary.get_actor_reference(
                    "PersistentLevel.%s" % objective_destructible_label)

                if not objective:
                    objective = create_objective_destructible(objective_destructible_label,
                                                              controlpoint_destructible_info["origin"],
                                                              controlpoint_destructible_info["angles"],
                                                              asset_path="/Game/Game/Actors/Objectives/Obj_WeaponCache_Ins")

                    # Ensure objective destructible
                    sublevels[gamemode]["actors"].append(objective)

            # Add this Objective(Capturable/Destructible) to our objectives list!
            if objective:
                print("[*] Attempting to add objects for gamemode: %s - objective %s" % (gamemode, num_to_alpha(index)))
                if "objective_based_spawns" in sublevels[gamemode] and sublevels[gamemode]["objective_based_spawns"]:
                    try:
                        objective_info = unreal.ObjectiveInfo(objective, sublevels[gamemode]["objective_based_spawns"][index])
                    except Exception as ex:
                        print("[!] COULDN'T FIND SPAWN FOR OBJECTIVE: (%s,%s) - ERR: %s" % (
                            objective.get_name(), num_to_alpha(index), str(ex)))
                        if index > 0:
                            print("[!] USING SPAWNS FROM OBJECTIVE %s AS REPLACEMENT" % num_to_alpha(index-1))
                            objective_info = unreal.ObjectiveInfo(objective, sublevels[gamemode]["objective_based_spawns"][index-1])
                        else:
                            print("[!] NO SPAWNS CREATED FOR OBJECTIVE %s" % num_to_alpha(index))
                            objective_info = unreal.ObjectiveInfo(objective, [])
                else:
                    # This must be a PVP only gamemode since there weren't any objective_based_spawns (for AI)
                    objective_info = unreal.ObjectiveInfo(objective, [])
                sublevels[gamemode]["objectives"].append(objective_info)
            else:
                print("[!] WTF?! No objectives parsed for controlpoint: %s" % controlpoint_name)

    # ------------------------------------ 2. Create misc entities! (like SupplyCrates)
    if "entities" in gamemode_info:
        for entity_key, entity in gamemode_info["entities"].items():
            if entity_key.startswith("obj_ammo_crate"):
                sc = create_supply_crate(entity["targetname"], entity["origin"], entity["angles"])
                sublevels[gamemode]["actors"].append(sc)


    print("[*] SPAWNS THAT EXIST: {}".format(list(spawns_that_exist.keys())))

    return True


def create_scenario_asset(scenario_name, objectives, attacking_team=255, map=None, sublevels=None,
                          game_mode=None, persistent_level_world=None, default_threater=None,
                          neutral_spawnzones=None, ui_display_name=None, scenario_type=None):
    """ Creates a Scenario for the *current world*, based on the provided scenario_name or values.
        Our "objectives" should be a list of unreal.ObjectiveInfo objects
    """

    if not persistent_level_world:
        # Get current level and path
        persistent_level_world = unreal.EditorLevelLibrary.get_editor_world()

    # The path (/DOISourceMapPack/Maps/Bastogne") split by / with blanks removed
    persistent_level_asset_path_split = list(filter(
        lambda x: x, persistent_level_world.get_outer().get_name().split("/")))

    # The name of the current open Level, IE: Bastogne
    current_map_name = persistent_level_asset_path_split[-1]
    scenario_map_name = scenario_name.replace("Scenario_", "")

    # Get the root game path, IE: /DOISourceMapPack/
    root_game_dir = "/%s/" % persistent_level_asset_path_split[0]
    scenarios_dir = root_game_dir + "Scenarios"

    # Make sure the "Scenarios" directory exists
    if not unreal.EditorAssetLibrary.does_directory_exist(scenarios_dir):
        unreal.EditorAssetLibrary.make_directory(scenarios_dir)

    # Put together the asset path to this scenario
    scenario_asset_path = "%s/%s" % (scenarios_dir, scenario_name)

    # If this scenario already exists, we won't change it -- just return it
    if unreal.EditorAssetLibrary.does_asset_exist(scenario_asset_path):
        scenario = unreal.EditorAssetLibrary.find_asset_data(scenario_asset_path).get_asset()
        print("[*] Scenario '%s' already exists! We'll modify it ..." % scenario_asset_path)
    else:
        # Attempt to create our new scenario asset
        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
        scenario = asset_tools.create_asset(
            asset_name=scenario_name,
            package_path=scenarios_dir,
            asset_class=scenario_type if scenario_type else unreal.ScenarioMultiplayer,
            factory=unreal.ScenarioAssetFactory())
    if not scenario:
        raise ValueError("failed to create scenario: %s" % scenario_name)

    # Set the Scenario's "Level" value to the currently loaded level
    scenario.set_editor_property("level", persistent_level_world)

    # Assume we wanted to create a Checkpoint map if we didn't specify ...
    if game_mode:
        scenario.set_editor_property("game_mode", game_mode)
    else:
        if "Checkpoint" in scenario_name:
            scenario.set_editor_property("game_mode", unreal.INSCheckpointGameMode)
            attacking_team = 0 if "Security" in scenario_name else 1
            ui_display_name = "Security" if "Security" in scenario_name else "Insurgents"
        elif "Domination" in scenario_name:
            scenario.set_editor_property("game_mode", unreal.DominationGameMode)
            attacking_team = 255
        elif "Firefight" in scenario_name:
            scenario.set_editor_property("game_mode", unreal.INSFirefightGameMode)
            attacking_team = 255
            ui_display_name = "East" if "East" in scenario_name else "West"
        elif "Push" in scenario_name:
            scenario.set_editor_property("game_mode", unreal.INSPushGameMode)
            attacking_team = 0 if "Security" in scenario_name else 1
            ui_display_name = "Security" if "Security" in scenario_name else "Insurgents"
        elif "Deathmatch" in scenario_name:
            scenario.set_editor_property("game_mode", unreal.INSTeamDeathmatchGameMode)
            attacking_team = 255
        else:
            raise ValueError("wtf kind of scenario name is '%s'?! Gib moar code so I understand!!" % scenario_name)

    # *Always* set attacking team
    # If the attacking team == 0 (Security), we can't use "if attacking_team:"
    # because 0 == None in Python *shrugs*
    scenario.set_editor_property("attacking_team", attacking_team)

    # "Map" is just the name of this map, IE: Bastogne
    if map:
        scenario.set_editor_property("map", map)
    else:
        scenario.set_editor_property("map", current_map_name)

    # These are usually only used in Versus and Survival
    if neutral_spawnzones:
        scenario.set_editor_property("neutral_spawn_zones", neutral_spawnzones)

    if ui_display_name:
        scenario.set_editor_property("scenario_name", ui_display_name)

    if default_threater:
        scenario.set_editor_property("default_theater", default_threater)
    else:
        # Get the default TheaterDefinition: THTR_SecurityInsurgents
        threater_asset_path = "/Game/Game/Factions/Theaters/THTR_SecurityInsurgents"
        threater_asset_data = unreal.EditorAssetLibrary.find_asset_data(threater_asset_path).get_asset()
        scenario.set_editor_property("default_theater", threater_asset_data)

    # Define all sublevels the server should load.
    # This only needs to be the sublevel for this gamemode, really.
    # Lighting is set in the World settings
    if sublevels:
        scenario.set_editor_property("sublevels",  sublevels)
    else:
        # Add only this sublevel, unless this is a Checkpoint scenario,
        # then we'll add a Hardcore level (since it doesn't require an
        # actual sublevel -- it just uses the Checkpoint level)
        sublevels = [unreal.ScenarioSublevel(scenario_map_name)]
        if "Checkpoint" in scenario_name:
            scenario_hardcore_name = scenario_map_name.replace("Checkpoint", "Checkpoint_Hardcore")
            sublevels.append(unreal.ScenarioSublevel(
                scenario_hardcore_name,
                use_with_specified_game_modes_only=True,
                specified_game_modes=[unreal.INSCheckpointHardcoreGameMode]
            ))
        scenario.set_editor_property("sublevels", sublevels)

    # Set the objectives for this scenario
    if objectives:
        scenario.set_editor_property("objectives", objectives)

    return scenario


def ensure_sublevels_exist(sublevel_tags, persistent_level_world=None):

    if not persistent_level_world:
        # Get current level and path
        persistent_level_world = unreal.EditorLevelLibrary.get_editor_world()

    root_level_asset_path = persistent_level_world.get_outer().get_name()
    root_level_name = persistent_level_world.get_name()

    # Create levels for Tools, Decals, Notes, etc...
    sublevels = {
        tag: {
            "actors": list(),
            "asset_path": "%s_%s" % (root_level_asset_path, tag),
            "name": "%s_%s" % (root_level_name, tag)
        }
        # Each tag defined in this list creates a sublevel
        for tag in sublevel_tags
    }

    total_frames = len(sublevels.keys() * 2)
    text_label = "Ensuring sublevels for '%s' exist..." % root_level_name
    with unreal.ScopedSlowTask(total_frames, text_label) as slow_task:
        slow_task.make_dialog(True)

        # Create sublevels if they don't already exist
        if not unreal.EditorAssetLibrary.do_assets_exist([sl["asset_path"] for sl in sublevels.values()]):

            # Create each level if it doesn't already exist
            for tag, sublevel in sublevels.items():

                if slow_task.should_cancel():
                    break

                unreal.EditorLevelLibrary.new_level(sublevel["asset_path"])

                slow_task.enter_progress_frame(work=1, desc="Creating sublevel: %s" % tag)

            # Reload main level since the above level creation unloads it
            unreal.EditorLevelLibrary.load_level(root_level_asset_path)

            # Set all newly created/existing levels as sublevels of our "Persistent Level"
            for tag, sublevel in sublevels.items():

                if slow_task.should_cancel():
                    break

                sublevel_stream = unreal.EditorLevelUtils.create_new_streaming_level(
                    unreal.LevelStreamingDynamic, sublevel["asset_path"],
                    move_selected_actors_into_new_level=False)
                sublevel["level"] = sublevel_stream  # .get_loaded_level()

                slow_task.enter_progress_frame(work=1, desc="Adding sublevel '%s' to PersistentLevel" % tag)

            print("-------------------------------")
            print("  MISSING SUBLEVELS CREATED")
            print("-------------------------------")
            #unreal.EditorDialog().show_message(
            #    title="INFO",
            #    message="Sublevels have been created. Please re-run this script to continue.",
            #    message_type=unreal.AppMsgType.OK)
            main()

            print("-------------------------------")
            print("  Quitting script ...")
            print("-------------------------------")
            exit(0)

        else:

            # All sublevels already exist.
            # We need a reference to these streaming levels
            for tag, sublevel in sublevels.items():

                if slow_task.should_cancel():
                    break

                sublevel["level"] = unreal.GameplayStatics.get_streaming_level(
                    persistent_level_world, sublevel["name"])

                # Check if the above failed -- likely meaning we need to re-add the
                # streaming level
                if not sublevel["level"]:
                    sublevel_stream = unreal.EditorLevelUtils.create_new_streaming_level(
                        unreal.LevelStreamingDynamic, sublevel["asset_path"],
                        move_selected_actors_into_new_level=False)
                    sublevel["level"] = sublevel_stream  # .get_loaded_level()

                slow_task.enter_progress_frame(work=2, desc="Adding sublevel '%s' to PersistentLevel" % tag)

        # Make sure our "Persistent Level" is set as the "current" level
        unreal.EditorLevelLibrary.set_current_level_by_name(root_level_name)

    return sublevels


def merge_mesh_actors():
    # TODO: Figure out how to merge while keeping World Vertex blending :/
    terrain_meshes = list()
    actors = get_all_actors(actor_class=unreal.StaticMeshActor)
    for actor in actors:
        if not actor:
            continue
        if "_singlemesh_" not in actor.get_actor_label():
            continue
        if actor_contains_material_starting_with(actor, "doi_terrain"):
            terrain_meshes.append(actor)
    unreal.EditorLevelLibrary.set_selected_level_actors(terrain_meshes)


def give_debug_info():
    world = unreal.EditorLevelLibrary.get_editor_world()
    world_name = world.get_name()
    map_info = get_json_values_for_current_map(world)
    generate_entity_spreadsheets(open_directory=False)
    get_vmf_data_for_current_map(world_name,
      debug_output_path=r"%s.vmf.json" % world_name)
    json.dump(map_info, open("%s.txt.json" % world_name, "w"), indent=4)
    os.system("explorer %s.txt.json" % world_name)


def debug_selected_cover_actor():

    # Get the current world
    world_context_object = unreal.EditorLevelLibrary.get_editor_world()

    cover_actor = unreal.EditorLevelLibrary.get_selected_level_actors()[0]
    if isinstance(cover_actor, unreal.Note):

        convert_note_to_nbot_cover({"actor": cover_actor, "note": get_note_actor_details(cover_actor)},
                                   fire_from_feet=False)

    else:

        # Make sure our new AICoverActor isn't overlapping with any objects
        # by moving it out of the way of objects it overlaps with!
        for dir in ["forward", "right", "left", "diags"]:
            raycast_reposition_on_hit(cover_actor, world_context_object, direction=dir)

        # Reposition to the ground, changing our stance if the ground
        # is *very* close to the position we were spawned in
        stance = unreal.SoldierStance.STAND
        hit_something_below, distance = raycast_reposition_on_hit(cover_actor, world_context_object, "down")
        if hit_something_below:
            if distance < 220:
                stance = unreal.SoldierStance.CROUCH
            elif distance < 160:
                stance = unreal.SoldierStance.PRONE

        # If our AICoverActor is overlapping with something above it, make it crouch!
        hit_something_above, distance = raycast_reposition_on_hit(cover_actor, world_context_object, "up")
        if hit_something_above:
            print("dist to hit above: %d" % distance)
            if distance < 270:
                stance = unreal.SoldierStance.CROUCH
            elif distance < 180:
                stance = unreal.SoldierStance.PRONE

        # new_actor is an AICoverActor, which has
        # a "Cover" component. The "Cover" component
        # can define the stance, protection angle, launcher priority (good rocket launcher position?),
        # scope priority (is this a good sniper position?), machine gunner priority,
        # "ambush node" (good ambush position?), and "rank" (how important it is to bots)
        cover_component = cover_actor.get_component_by_class(unreal.CoverComponent)
        cover_component.set_editor_properties({
            "stance": stance,
        })


def delete_all_with_selected_mesh():
    """ Debug delete all with same mesh as selected StaticMesh (with Undo support) """
    selected_actors = unreal.EditorLevelLibrary.get_selected_level_actors()
    if selected_actors:
        with unreal.ScopedEditorTransaction("Deleted Same Meshes") as trans:
            all_actors = get_all_actors(actor_class=unreal.StaticMeshActor)
            meshes_of_actors_to_remove = list()
            for actor in selected_actors:
                if isinstance(actor, unreal.StaticMeshActor):
                    smc = actor.get_component_by_class(unreal.StaticMeshComponent)
                    mesh = smc.static_mesh
                    if mesh not in meshes_of_actors_to_remove:
                        meshes_of_actors_to_remove.append(smc.static_mesh)
            for actor in all_actors:
                smc = actor.get_component_by_class(unreal.StaticMeshComponent)
                mesh = smc.static_mesh
                if mesh in meshes_of_actors_to_remove:
                    actor.modify()
                    unreal.EditorLevelLibrary.destroy_actor(actor)


def remove_collision_from_all_with_mesh_prefix(mesh_name_prefix):
    """ Debug delete all with same mesh as selected StaticMesh (with Undo support) """
    with unreal.ScopedEditorTransaction("Removed Collision on Matching Meshes") as trans:
        for actor in get_all_actors(actor_class=unreal.StaticMeshActor):
            smc = actor.get_component_by_class(unreal.StaticMeshComponent)
            static_mesh = smc.static_mesh
            if not static_mesh.get_name().startswith(mesh_name_prefix):
                continue

            # Enable Complex as Simple for this physics object
            collision_complexity = unreal.EditorStaticMeshLibrary.get_collision_complexity(static_mesh)
            if collision_complexity != unreal.CollisionTraceFlag.CTF_USE_DEFAULT:
                print("[*] SM '%s' wasn't using Default collision complexity -- fixing" % static_mesh.get_name())
                static_mesh.modify()
                body_setup = static_mesh.get_editor_property("body_setup")
                body_setup.set_editor_property("collision_trace_flag",
                                               unreal.CollisionTraceFlag.CTF_USE_DEFAULT)
                static_mesh.set_editor_property("body_setup", body_setup)


def descale_and_position_non_skybox_actors():
    selected_actors = unreal.EditorLevelLibrary.get_selected_level_actors()
    if selected_actors:
        with unreal.ScopedEditorTransaction("Deleted Same Meshes") as trans:
            for actor in selected_actors:
                actor_location = actor.get_actor_location()
                # Move this actor to it's original world origin - it's position
                actor_location = actor_location / unreal.Vector(-16, -16, -16)
                actor.set_actor_location(actor_location, sweep=False, teleport=True)
                actor.set_actor_scale3d(unreal.Vector(1, 1, 1))


def move_gamelogic_actors_to_level():
    gamelogic_actors = list()
    gamelogic_actor_types = [
        unreal.INSPlayerStart,
        unreal.INSSpawnZone,
        unreal.INSDestructibleObjective,
        unreal.INSCaptureObjective,
        unreal.INSObjective,
        unreal.INSPatrolArea,
        unreal.INSRestrictedArea,
        unreal.INSVehicle,
        unreal.INSVehicleSpawner,
        unreal.CaptureZone,
        unreal.ObjectiveCapturable,
        unreal.ObjectiveDestructible,
        unreal.SpawnZone,
        unreal.SpawnerBase,
        unreal.SpawnerSquad,
        unreal.SpawnerVehicle,
        unreal.SpawnZoneCounterAttack,
        "Obj_WeaponCache",
        "BP_Supply"
    ]
    for actor in get_all_actors():
        if not actor:
            continue
        for gamelogic_actor_type in gamelogic_actor_types:
            if isinstance(gamelogic_actor_type, str):
                if gamelogic_actor_type in str(actor.get_class()):
                    print(" - adding: %s" % actor.get_actor_label())
                    gamelogic_actors.append(actor)
                    actor.modify()
            else:
                if isinstance(actor, gamelogic_actor_type):
                    print(" - adding: %s" % actor.get_actor_label())
                    gamelogic_actors.append(actor)
    unreal.EditorLevelLibrary.set_selected_level_actors(gamelogic_actors)


def hide_mannequins():

    # Hide all actors with a material name starting with "player_flesh_mat"
    # and return a list of all matching actors
    matching_actors = hide_all_actors_with_material_name("_flesh_")

    # Add all actors in the "actors_to_group" list to an Unreal group
    with unreal.ScopedEditorTransaction("Group Mannequins"):

        useless_actors_group = unreal.ActorGroupingUtils(name="Mannequins")
        useless_actors_group.group_actors(matching_actors)

        # Move actors to a folder called "Mannequins"
        move_actors_to_folder(matching_actors, "Mannequins")


def fix_materials(content_root=None):
    """ Get a list of all assets that are material instances. """

    if not content_root:
        # Get current level and path
        persistent_level_world = unreal.EditorLevelLibrary.get_editor_world()
        root_level_asset_path = persistent_level_world.get_outer().get_full_name().split(" ", 1)[-1]
        content_root = "/%s/" % root_level_asset_path.split("/")[1]

    assets = unreal.EditorAssetLibrary.list_assets(content_root, recursive=True)
    text_label = "Fixing all Material assets"
    total_frames = len(assets)
    with unreal.ScopedSlowTask(total_frames, text_label) as slow_task:
        slow_task.make_dialog(True)

        for i, asset_path in enumerate(assets):

            if slow_task.should_cancel():
                break

            slow_task.enter_progress_frame(1)

            if asset_path.endswith("toolsnodraw_mat"):

                asset_data = unreal.EditorAssetLibrary.find_asset_data(asset_path)
                material_asset = asset_data.get_asset()
                # material_asset.modify(True)

                # Retrieve NWI's T_UI_Empty texture (just a texture with full alpha)
                empty_texture = unreal.EditorAssetLibrary.find_asset_data("/Game/UI/Textures/T_UI_Empty")
                empty_texture2d = empty_texture.get_asset()

                # Get the first texture defined in this material's Texture Parameter Values section
                texture2d = material_asset.texture_parameter_values[0].parameter_value
                if texture2d != empty_texture2d:

                    # TODO: Create a new material instance using this texture instead of complaining!
                    print("[!] YOU MUST MANUALLY CHANGE THE SETTINGS BELOW!!!!!!!!!")
                    #unreal.EditorDialog().show_message(
                    #    title="INFO",
                    #    message="%s must use the texture '%s' and BlendMode == TRANSPARENT" %
                    #                 (material_asset.get_full_name(), empty_texture2d.get_full_name()),
                    #    message_type=unreal.AppMsgType.OK)
                    raise ValueError("%s must use the texture '%s' and BlendMode == TRANSPARENT" %
                                     (material_asset.get_name(), empty_texture2d.get_name()))

                '''
                # Set Basecolor texture to the "T_UI_Empty" texture
                # material_asset.texture_parameter_values[0].parameter_value = empty_texture2d
                unreal.MaterialEditingLibrary.set_material_instance_texture_parameter_value(
                    material_asset, "base_color", empty_texture2d)

                # Set the Blend Mode to Translucent
                overrides = material_asset.get_editor_property("base_property_overrides")
                overrides.set_editor_property("override_blend_mode", True)
                overrides.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
                unreal.MaterialEditingLibrary.set_editor_property(
                    material_asset, "base_property_overrides", overrides)
                '''


def fix_skybox_actors(skybox_actors_dict, sky_camera_actor=None):
    """ Attempt to resize and reposition all skybox actors as a 3D skybox would """
    sky_camera_actor = sky_camera_actor if sky_camera_actor else get_sky_camera()
    sky_camera_actor_location = sky_camera_actor.get_actor_location()

    for skybox_actor in skybox_actors_dict.values():

        # If this skybox actor appears to have already been moved, skip it
        if skybox_actor.get_parent_actor() == skybox_actor:
            continue

        # Attach this skybox actor to the sky_camera
        skybox_actor.attach_to_actor(sky_camera_actor, "root",
            location_rule=unreal.AttachmentRule.KEEP_RELATIVE,
            rotation_rule=unreal.AttachmentRule.KEEP_RELATIVE,
            scale_rule=unreal.AttachmentRule.KEEP_RELATIVE,
            weld_simulated_bodies=False)

        # Some skybox actor meshes have *really* messed up UVs due to
        # float point precision errors.
        # We'll enable the "use_full_precision_u_vs" MeshBuildSettings LOD property to fix these UV issues
        """
        if isinstance(skybox_actor, unreal.StaticMeshActor):

            static_mesh_component = skybox_actor.get_component_by_class(unreal.StaticMeshComponent)
            if not static_mesh_component:
                continue

            # FIX ONLY WORKS IN UE 4.26.X AND UP :(
            # Fix broken UVs caused by crazy large float offsets
            #lod_build_settings = unreal.EditorStaticMeshLibrary.get_lod_build_settings(static_mesh_component.static_mesh, 0)
            #lod_build_settings.set_editor_property("use_full_precision_u_vs", True)
            #unreal.EditorStaticMeshLibrary.get_lod_build_settings(static_mesh_component.static_mesh, 0, lod_build_settings)
        """

    # Move sky_camera to the world origin - it's position
    sky_camera_actor_location = sky_camera_actor_location * unreal.Vector(-16, -16, -16)
    sky_camera_actor.set_actor_location(sky_camera_actor_location, sweep=False, teleport=True)
    sky_camera_actor.set_actor_scale3d(unreal.Vector(16, 16, 16))


def fix_skybox(actors, skybox_bounds):
    total_frames = 2
    text_label = "Fixing 3D Skybox..."

    with unreal.ScopedSlowTask(total_frames, text_label) as slow_task:
        slow_task.make_dialog(True)

        # Find all Skybox actors - to be moved to the Skybox sublevel
        # (get_skybox_actors will remove skybox actors from the "actors" list passed in)
        try:
            sky_camera_actor = get_sky_camera()
            skybox_actors = get_skybox_actors(sky_camera_actor=sky_camera_actor, actors_to_search=actors,
                                              max_distance_to_skybox=skybox_bounds, remove_if_found=True)
            slow_task.enter_progress_frame(1)

            # Fix skybox actors by moving and resizing them.
            # Source Engine did this with camera tricks.
            # We'll do it the lazy way to keep things simple
            fix_skybox_actors(skybox_actors, sky_camera_actor=sky_camera_actor)
            slow_task.enter_progress_frame(1)
        except Exception as ex:
            print("[*] Couldn't find sky_camera actor; skybox already fixed???")
            return None
        return skybox_actors


def fix_all_actor_parents():

    actors = {str(actor.get_actor_label()): actor for actor in unreal.EditorLevelLibrary.get_all_level_actors()}
    for actor_label, actor in actors.items():

        # We'll only work on StaticMeshActors
        if not isinstance(actor, unreal.StaticMeshActor):
            continue

        # Check if an actor with this name (without "_physics" or "_reference")
        # exists and parent this actor to
        if CHILD_OBJECT_REGEX.match(actor_label):

            real_mesh_actor_name = actor_label.rsplit("_", 1)[0]
            real_mesh_actor = actors[real_mesh_actor_name] if real_mesh_actor_name in actors else None
            if not real_mesh_actor:
                real_mesh_actor_name = actor_label.rsplit("_", 2)[0]
                real_mesh_actor = actors[real_mesh_actor_name] if real_mesh_actor_name in actors else None
            if real_mesh_actor:

                print("[*] Parent '%s' to '%s'" % (actor.get_actor_label(), real_mesh_actor.get_actor_label()))
                actor.attach_to_actor(
                    real_mesh_actor,  # Actor to attach to
                    "root",  # Socket on parent
                    unreal.AttachmentRule.KEEP_WORLD,  # Location
                    unreal.AttachmentRule.KEEP_WORLD,  # Rotation
                    unreal.AttachmentRule.KEEP_WORLD,  # Scale
                    False)

                # Check if the "real" mesh actor is barbed wire --
                # if so, generate simple box collision for the barbed wire
                real_actor_mesh = real_mesh_actor.get_component_by_class(unreal.StaticMeshComponent).static_mesh
                if "barbed_wire_" in real_actor_mesh.get_name():
                    real_mesh_has_collider = unreal.EditorStaticMeshLibrary.get_convex_collision_count(real_actor_mesh) > 0 \
                                             or unreal.EditorStaticMeshLibrary.get_simple_collision_count(
                        real_actor_mesh) > 0
                    if not real_mesh_has_collider:
                        # Add a simple box collider for this mesh
                        unreal.EditorStaticMeshLibrary.add_simple_collisions(
                            real_actor_mesh, unreal.ScriptingCollisionShapeType.BOX)


def fix_actor_parent(actor, static_mesh_name, static_mesh_type, static_mesh, static_mesh_actors):
    """Parent a "physics" type to it's "reference" type, if applicable
       Parent a "physics" type to it's regular type, if applicable"""
    parent_actor = actor.get_attach_parent_actor()
    if not parent_actor:
        return

    # If parent actor is the root Datasmith level Actor ...
    if parent_actor.get_name()[-2:] == "_d":

        print("[*] %s: %s" % (static_mesh_type, static_mesh_name))
        if static_mesh_type == "physics":

            # Enable Complex as Simple for this physics object
            collision_complexity = unreal.EditorStaticMeshLibrary.get_collision_complexity(static_mesh)
            if collision_complexity != unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE:
                print("[*] %s has no collision -- fixing" % actor.get_name())
                body_setup = static_mesh.get_editor_property("body_setup")
                body_setup.set_editor_property("collision_trace_flag", unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE)
                static_mesh.set_editor_property("body_setup", body_setup)

            # Check if an actor with this name (without "_physics" or "_reference")
            # exists and parent this actor to
            real_mesh_actor_name = static_mesh_name[:-len(static_mesh_type)-1]
            real_mesh_actor = static_mesh_actors[real_mesh_actor_name] if real_mesh_actor_name in static_mesh_actors else None
            if real_mesh_actor:

                real_mesh_actor = static_mesh_actors[real_mesh_actor_name]["actor"]
                print("[*] Parent '%s' to '%s'" % (actor.get_name(), real_mesh_actor.get_name()))
                actor.attach_to_actor(
                    real_mesh_actor,  # Actor to attach to
                    "root",  # Socket on parent
                    unreal.AttachmentRule.KEEP_WORLD,  # Location
                    unreal.AttachmentRule.KEEP_WORLD,  # Rotation
                    unreal.AttachmentRule.KEEP_WORLD,  # Scale
                    False)

                # Check if the "real" mesh actor is barbed wire --
                # if so, generate simple box collision for the barbed wire
                real_actor_mesh = real_mesh_actor.get_component_by_class(unreal.StaticMeshComponent).static_mesh
                if "barbed_wire_" in real_actor_mesh.get_name():
                    real_mesh_has_collider = unreal.EditorStaticMeshLibrary.get_convex_collision_count(real_actor_mesh) > 0 \
                                   or unreal.EditorStaticMeshLibrary.get_simple_collision_count(real_actor_mesh) > 0
                    if not real_mesh_has_collider:

                        # Add a simple box collider for this mesh
                        unreal.EditorStaticMeshLibrary.add_simple_collisions(
                            real_actor_mesh, unreal.ScriptingCollisionShapeType.BOX)


def fix_collisions(static_mesh_actors=None):
    pass


def fix_decals(decal_material_asset_data):
    pass


def fix_all_lighting():

    # Attempt to find the actor labeld "_lights_set",
    # and fix *normal* lights (no directional) if this actor doesn't exist yet
    light_multiplier = 2
    if not unreal.EditorLevelLibrary.get_actor_reference("PersistentLevel._lights_set_"):

        # Fix lights! They should all be multiplied by 10 once
        for light_actor in get_all_actors(actor_class=unreal.Light):
            for light_class in [unreal.PointLightComponent, unreal.SpotLightComponent]:
                try:
                    light_component = light_actor.get_component_by_class(light_class)
                    if not light_component:
                        continue
                    try:
                        light_actor.modify()
                        intensity = light_component.get_editor_property("intensity")
                        light_component.set_editor_property("intensity", intensity * light_multiplier)
                    except:
                        pass
                except:
                    pass
        # Create the actor that will notify us *not* to run this if
        # we run this script again.
        note = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.Note, unreal.Vector(0, 0, 0))
        note.set_editor_property("text", "all point and spot lights set to their value * %d" % light_multiplier)
        note.set_actor_label("_lights_set_")

    return


def fix_everything(world, map_info, map_data, skybox_bounds=6000):
    """ Create a separate sublevels for notes, tools, etc... """

    # Get the name of the current level's root name, which
    # should be the name of the mod (DOISourceMapPack)
    world_mod_name = get_world_mod_name(world)
    content_root = "/{}/DOI".format(world_mod_name)

    # Make the "toolsnodraw_mat" material invisible!
    fix_materials(content_root)

    # Find and store all actor references in memory ...
    actors = get_all_actors()

    # Delete all useless skybox actors
    for actor in actors:
        if actor_contains_material_starting_with(actor, "toolsskybox"):
            print("[!] DELETE SKYBOX BOX: %s" % actor.get_name())
            unreal.EditorLevelLibrary.destroy_actor(actor)

    # Get valid gamemodes to create sublevels and scenarios for
    # TODO: Parse gamemodes from translated keys in map_json
    valid_gamemodes = [

        # PVP  ----------------
        # "Push", "Firefight", "Domination",

        # COOP ----------------
        "Checkpoint_Security" if map_info["stronghold"]["AttackingTeam"] == 0 else "Checkpoint_Insurgents"

    ]

    # Ensure all sublevels defined below exist
    # for the currently open PersistentLevel
    sublevels = ensure_sublevels_exist([

        # Custom sublevels for organization
        "Skybox", "Tools", "Decals", "Notes",
        "Soundscape", "AI", "BlockingVolumes", "Misc",

        # Lighting  -----------
        "GlobalDay",

    ] + valid_gamemodes)

    # Hide the following levels using horribly complex and inefficient code
    tags_to_hide = ["Notes", "Tools"] + valid_gamemodes
    levels_to_hide = list(filter(lambda kl: kl[0] in tags_to_hide, [(k, s["level"].get_loaded_level()) for k, s in sublevels.items()]))
    unreal.EditorLevelUtils.set_levels_visibility(
        [kl[1] for kl in levels_to_hide],
        [False for i in range(0, len(levels_to_hide))],
        False)

    # Find, reposition, and rescale our 3D skybox
    skybox_actors = fix_skybox(actors, skybox_bounds=skybox_bounds)
    if skybox_actors:
        unreal.EditorLevelUtils.move_actors_to_level(
            skybox_actors.values(), sublevels["Skybox"]["level"],
            warn_about_references=False,
            warn_about_renaming=False)

    # Remove this sublevel as we've already moved its actors
    sublevels.pop("Skybox")

    # Parse all found actors and throw them in their proper sublevels
    # -- also parse and replace actors with their Sandstorm equivalents
    total_frames = len(actors)
    text_label = "Adding actors to their proper sublevels..."
    with unreal.ScopedSlowTask(total_frames, text_label) as slow_task:
        slow_task.make_dialog(True)

        # Iterate over all actors in the Persistent level (minus the skybox actors
        # we removed above in the get_skybox_actors function)
        for i, actor in enumerate(actors):

            if slow_task.should_cancel():
                break

            slow_task.enter_progress_frame(work=1)

            # Skip null ObjectInstance actors
            # (which trigger: Exception: WorldSettings: Internal Error - ObjectInstance is null!)
            if not actor:
                continue

            # Store the actor's label (what we see as it's name in the World Outliner)
            try:
                actor_label = actor.get_actor_label()
            except:
                print("[!] Failed to get an actor label for actor index: %d" % i)
                continue

            # Ensure this actor's label is in our "PLACED_ACTORS" set,
            # so we don't attempt to duplicate it anywhere
            # (for instance, when spawning new AICoverActors)
            PLACED_ACTORS.add(actor_label)

            # If this actor isn't in PersistentLevel, skip it
            # as it's already in a sublevel (and normally wouldn't be
            # unless we put it there on purpose)
            actor_level = actor.get_outer()
            actor_level_name = actor_level.get_name()
            if actor_level_name != "PersistentLevel":
                print("[!] Actor '%s' in '%s' -- not PersistentLevel -- skipping..." %
                      actor.get_actor_label(), actor_level_name)
                continue

            # Check if this actor is an "unknown" entity
            if actor_label.startswith("entity_unknown") \
                    or actor_contains_material_starting_with(actor, "M_missingProp"):

                if actor_contains_material_starting_with(actor, "M_missingProp"):

                    # Disable collision on this tool object!
                    actor.set_actor_enable_collision(False)

                    # Make sure this tool is hidden in the editor
                    actor.set_actor_hidden_in_game(True)

                # Add this unknown actor to the "actors" array to be sent
                # to the "Misc" sublevel
                sublevels["Misc"]["actors"].append(actor)

            elif (actor_contains_material_starting_with(actor, "tools")
                or actor_contains_material_starting_with(actor, "fogvolume")):

                if actor_contains_material_starting_with(actor, "toolsblack"):
                    continue

                # Disable collision on this tool object if it's not a clipping/blocking object
                smc = actor.get_component_by_class(unreal.StaticMeshComponent)
                if actor_contains_material_starting_with(actor, "toolsplayerclip"):
                    actor.set_actor_enable_collision(True)
                    smc.set_collision_profile_name("OverlapOnlyPawn")
                else:
                    actor.set_actor_enable_collision(False)
                    if smc:
                        smc.set_collision_profile_name("NoCollision")

                # Make sure this tool is hidden in-game
                actor.set_actor_hidden_in_game(True)

                sublevels["Tools"]["actors"].append(actor)

            elif isinstance(actor, unreal.DecalActor):

                # Add this DecalActor to the "actors" array to be sent
                # to the "Decals" sublevel
                sublevels["Decals"]["actors"].append(actor)

            elif isinstance(actor, unreal.Note):

                # This note type wasn't parsed (we couldn't determine it's type)
                # Add this Note actor to the "actors" array to be sent
                # to the "Notes" sublevel
                sublevels["Notes"]["actors"].append(actor)

            elif actor_contains_named_mesh(actor, "wall_trim_b"):

                # Delete this actor! wall_trim_b is a disgustingly broken
                # model after importing with HammUEr :(
                unreal.EditorLevelLibrary.destroy_actor(actor)

            elif actor_label.startswith("entity_light") \
                or isinstance(actor, unreal.DirectionalLight) \
                or isinstance(actor, unreal.LightmassImportanceVolume) \
                or isinstance(actor, unreal.SkyLight) \
                or isinstance(actor, unreal.SphereReflectionCapture) \
                or "Sky Sphere" in actor_label:

                # Force Movable (dynamic lighting)
                actor.root_component.set_mobility(unreal.ComponentMobility.MOVABLE)
                # actor.set_mobility(unreal.ComponentMobility.MOVABLE)
                
                # Move light to GlobalDay sublevel
                sublevels["GlobalDay"]["actors"].append(actor)

        # Parse all notes and create their UE4/Sandstorm equivalents
        parse_note_actors(sublevels["Notes"]["actors"], sublevels)

        # Create scenarios
        world_settings_default_scenarios = list()
        for gamemode in valid_gamemodes:

            # Skip gamemodes we said are valid but we didn't create a sublevel for
            if gamemode not in sublevels:
                print("[!] Gamemode '%s' isn't in sublevels -- skipping" % gamemode)
                continue

            # Create Sandstorm goodness! (Scenario, SpawnZone, INSPlayerStarts, etc...)
            if not create_gamemode_actors(gamemode, map_info, map_data, sublevels):
                # We ... failed?!? NANI?! Okay ... skip this gamemode
                print("[!] Failed to create gamemode actors for gamemode '%s' -- debugging time!" % gamemode)
                continue

            # Create the scenario for this gamemode!
            scenario_asset = create_scenario_asset(
                scenario_name="Scenario_%s" % sublevels[gamemode]["name"],
                objectives=sublevels[gamemode]["objectives"],
                neutral_spawnzones=sublevels[gamemode]["neutral_spawnzones"]
            )

            """
            # Oh joy -- more stupid Blueprint Read-Only properties ...
            if scenario_asset:
                # Make sure our World Settings has this scenario defined in
                # Default Scenarios
                default_scenario = unreal.DefaultScenarios()
                default_scenario.set_editor_properties({
                    "game_mode": scenario_asset.get_editor_property("game_mode"),
                    "scenario": scenario_asset})
                world_settings_default_scenarios.append(default_scenario)
            else:
                print("[!] WTF NO SCENARIO FOR GAMEMODE: %s" % gamemode)
            """

        # Define the default lighting scenario for our default level,
        # as well as the "Default Scenarios" setting with our list of scenarios
        """?!?!?! Can't set in Blueprints/Python?!?! Seriously?!?!?
        world_settings = world.get_world_settings()
        world_settings.set_editor_properties({
            "lighting_scenarios": {"Day": "%s_GlobalDay" % world.get_name()},
            "default_lighting_scenario": "Day",
            "default_scenarios": world_settings_default_scenarios
        })
        """

        # Create a HUUUGE NavMeshBoundsVolume and LightmassImportanceVolume to cover the map
        # TODO: Make sure to manually modify this! Add more than one, probably
        for vol_class in [unreal.NavMeshBoundsVolume, unreal.LightmassImportanceVolume]:
            label = "LightmassImportanceVolume" if vol_class == unreal.LightmassImportanceVolume else "NavMeshBoundsVolume"
            if label in PLACED_ACTORS:
                print("[*] The volume '%s' already exists; skipping creation ..." % label)
                continue
            vol = unreal.EditorLevelLibrary.spawn_actor_from_class(vol_class,
                                                                location=unreal.Vector(0, 0, 0),
                                                                rotation=unreal.Rotator(0, 0, 0))
            vol.set_actor_scale3d(unreal.Vector(300, 300, 20))
            vol.set_actor_label(label)
            if vol_class == unreal.LightmassImportanceVolume:
                sublevels["GlobalDay"]["actors"].append(vol)

        # Move all Tools, Decals, etc to their sublevels
        for sublevel_key, sublevel in sublevels.items():
            try:
                print("[*] Moving actors from {}.sublevel[\"actors\"] to: {}".format(sublevel_key, sublevel["level"]))
                print("--- ACTORS:")
                for actor in sublevel["actors"]:
                    try:
                        print(actor.get_name())
                    except:
                        pass
                
                # Move actors to their associated level
                unreal.EditorLevelUtils.move_actors_to_level(
                    sublevel["actors"], sublevel["level"],
                    warn_about_references=False,
                    warn_about_renaming=False)
            except Exception:
                traceback.print_exc()

    # Save all levels we modified!
    # unreal.EditorLevelLibrary.save_all_dirty_levels()

    # Fix lights! They should all be multiplied by ~8 once
    with unreal.ScopedEditorTransaction("Fix Lights"):
        fix_all_lighting()

    # Fix collisions!
    fix_collisions()

    # Hide mannequins
    hide_mannequins()

    # Fix decals!
    print("[*] Attempting to fix all decals ...")
    decal_material_asset_data = unreal.EditorAssetLibrary.find_asset_data("/%s/HammUErDecal" % world_mod_name)
    if not decal_material_asset_data:
        raise ValueError("[!] Couldn't find /%s/HammUErDecal" % world_mod_name)
    fix_decals(decal_material_asset_data)

    # MAKE THIS NOTE APPARENT!
    for i in range(0, 10):
        print("|")
    print("[!] SET DEFAULT LIGHTING AND SCENARIOS IN WORLD SETTINGS")
    print("[!] SET PROPER NAVMESH AND LIGHTMASSIMPORTANCE VOLUME SCALE/POSITION")
    print("[!] RESIZE SPAWNZONE TRIGGERS")
    print("[!] REPOSITION SPAWNPOINTS")
    for i in range(0, 4):
        print("|")

    #unreal.EditorDialog().show_message(
    #    title="INFO",
    #    message="Make sure so setup lighting and post-processing, resize the NavMesh, LightMassImportanceVolume and PlayArea, and repositition spawn zones.",
    #    message_type=unreal.AppMsgType.OK)


def main():

    # PER MAP SKYBOX BOUND VALUES:
    # Bastogne: 15000
    # Breville: 15000
    # Brittany: 8000
    # Brittany: 3500
    # Comacchio: 15000
    # Crete: 15000
    # DogRed: 15000
    # Dunkirk: 10000
    # Flakturm: 8000
    # Foy: 14000
    # Ortona: 10000
    # Reichswald: 13000
    # Rhineland: 9500
    # SaintLo: 9500
    # Salerno: 12000
    # ShootingRange: 0 (no skybox; skip step)
    # Sicily: 20000
    
    per_map_skybox_bounds = 20000

    # DEBUGGING:
    #give_debug_info()
    #generate_entity_spreadsheets(open_directory=True)
    #return
    #descale_and_position_non_skybox_actors()
    #return

    #move_gamelogic_actors_to_level()
    #return

    # DEBUGGING SKYBOX
    """
    actors = get_all_actors()
    sky_camera_actor = get_sky_camera()
    skybox_actors = get_skybox_actors(sky_camera_actor=sky_camera_actor, actors_to_search=actors,
                                      max_distance_to_skybox=per_map_skybox_bounds, remove_if_found=False, select_actors=True)
    return
    """

    #remove_collision_from_all_with_mesh_prefix("Urban_bush")
    #return

    # Debug raycast reposition if selected actor is an unreal.Note
    # selected_actors = unreal.EditorLevelLibrary.get_selected_level_actors()
    # if selected_actors and isinstance(selected_actors[0], unreal.Note):
    #    debug_selected_cover_actor()
    #    return
    #merge_mesh_actors()
    #return

    # Actually start!

    # Get the current world we have open in the editor,
    # which *should* be our HammUEr imported map
    world = unreal.EditorLevelLibrary.get_editor_world()
    world_name = world.get_name()

    # Attempt to retrieve the values from this Source map's .txt file
    # (exported by GCFScape).
    # We'll use this data to determine what game modes (Scenarios) to provide,
    # what objectives to place in said game mode (Scenarios), etc ...
    map_info = get_json_values_for_current_map(world)

    # Attempt to retrieve the values from this Source map's .vmf file
    # The VMF should contain data HammUEr doesn't correctly parse,
    # such as solids of classes it doesn't understand (IE: trigger_control_point)
    map_data = get_vmf_data_for_current_map(world_name)

    # Attempt to fix everything (and create scenarios, spawn objects, blah blah blah)
    fix_everything(world, map_info, map_data, skybox_bounds=per_map_skybox_bounds)

    print("[*] We're done! Almost everything should be fixed")


# Run main!
main()
