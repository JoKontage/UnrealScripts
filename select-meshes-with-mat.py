# Unreal Python script
# Attempts to fix various issues in Source engine Datasmith
# imports into Unreal
from collections import Counter, defaultdict, OrderedDict

import sys
import unreal
import re
import traceback
import os
import json
import csv
import posixpath
import math
from glob import glob



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


def get_selected_actors():
    """ return: obj List unreal.Actor : The selected actors in the world """
    return unreal.EditorLevelLibrary.get_selected_level_actors()


def main():

    script_path = sys.argv.pop(0)
    if len(sys.argv) == 0:
        return

    selected_actors = list()
    with unreal.ScopedEditorTransaction("Select Specific Meshes") as trans:
        for actor in unreal.EditorLevelLibrary.get_all_level_actors():
            for arg in sys.argv:
                if actor_contains_material(actor, arg):
                    selected_actors.append(actor)
                    break
        unreal.EditorLevelLibrary.set_selected_level_actors(selected_actors)

main()
