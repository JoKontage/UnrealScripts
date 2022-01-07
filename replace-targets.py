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


def actor_contains_material_starting_with(actor, material_name):
    """ If this actor is StaticMeshActor and contains a material with
        a name beginning with any of the words in the provided material_name,
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

            if mat_name.startswith(material_name):
                return True

    # Actor wasn't a StaticMesh or no materials matched
    return False


def get_selected_actors():
    """ return: obj List unreal.Actor : The selected actors in the world """
    return unreal.EditorLevelLibrary.get_selected_level_actors()


def point_actor_down(actor):
    # Reset actor rotation; which points down by default
    actor.set_actor_rotation(unreal.Rotator(0,-90,0), True)


def main():

    prop = "prop_target_metal_"
    with unreal.ScopedEditorTransaction("Select Specific Meshes") as trans:
        for actor in unreal.EditorLevelLibrary.get_all_level_actors():
            if isinstance(actor, unreal.StaticMeshActor):
                static_mesh_component = actor.get_component_by_class(unreal.StaticMeshComponent)

                # Skip if there's no static mesh to display
                if not static_mesh_component.static_mesh:
                    continue

                # Check if this static mesh is named whatever we
                # specified in our mesh_name variable
                mesh_name = static_mesh_component.static_mesh.get_name()
                if not mesh_name.startswith(prop):
                    continue

                # 1. Spawn new BP_Prop_Target with same transform as actor
                new_actor_label = actor.get_actor_label() + "_REPLACEMENT"
                actor_location = actor.get_actor_location()
                actor_rotation = actor.get_actor_rotation()
                new_target = spawn_blueprint_actor("/DOISourceMapPack/DynamicActors/BP_Target_Metal",
                                    label=new_actor_label,
                                    actor_location=actor_location,
                                    actor_rotation=actor_rotation,
                                    actor_scale=actor.get_actor_scale3d(),
                                    properties=dict())

                # 2. Replace BP_Prop_Target's mesh with actor mesh
                new_target_smc = actor.get_component_by_class(unreal.StaticMeshComponent)
                new_target_smc.set_static_mesh(static_mesh_component.static_mesh)

                # 3. Delete actor
                unreal.EditorLevelLibrary.destroy_actor(actor)

main()
