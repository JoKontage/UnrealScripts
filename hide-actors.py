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


def get_snake_case(text):
    # If world_name contains CamelCase lettering, add an _
    # before each uppercase letter following the first letter
    # TODO: This is a stupid way to do this, right? *Maybe* fix it .. but ... it *does* work ...
    text = "".join(reversed([c if c.islower() else "_%s" % c for c in reversed(text)]))

    # If world_name has a leading underscore, remove it
    text = text[1:] if text[0] == "_" else text

    # Ensure world_name is lowercase
    return text.lower()


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


def select_actors(actors_to_select=[]):
    """
    # Note: Will always clear the selection before selecting.
    # actors_to_select: obj List unreal.Actor : The actors to select.
    """
    unreal.EditorLevelLibrary.set_selected_level_actors(actors_to_select)


def get_selected_actors():
    """ return: obj List unreal.Actor : The selected actors in the world """
    return unreal.EditorLevelLibrary.get_selected_level_actors()



def actor_contains_material(actor, material_name, containing=False):
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


def hide_all_actors_with_material_name(material_name, containing=True):
    """ Hide all actors with the specified material (with Undo support) """
    matching_actors = list()

    with unreal.ScopedEditorTransaction("Hiding Actors (in-game) with Specific Mat") as trans:
        
        # Find all actors with the specified material and add them
        # to the "matching_actors" list.
        for actor in get_all_actors(actor_class=unreal.StaticMeshActor):

            if actor_contains_material(actor, material_name, containing=containing):
                print(" - hiding actor: %s" % actor.get_name())

                # Hide this specified actor in-game
                actor.set_actor_hidden_in_game(True)

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


def main():

    # Hide all actors with a material name starting with "player_flesh_mat"
    # and return a list of all matching actors
    matching_actors = hide_all_actors_with_material_name("_flesh_", containing=True)

    # Add all actors in the "actors_to_group" list to an Unreal group
    with unreal.ScopedEditorTransaction("Group Mannequins"):

        useless_actors_group = unreal.ActorGroupingUtils(name="Mannequins")
        useless_actors_group.group_actors(matching_actors)

        # Move actors to a folder called "Mannequins"
        move_actors_to_folder(matching_actors, "Mannequins")

    print("[*] We're done! Actors should be hidden in-game")


# Run main!
main()
