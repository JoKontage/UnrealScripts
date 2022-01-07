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


def reposition_to_first_below(actor, world, direction=None, raycast_distance=5000, ignore_classes=[], ignore_with_mats=None, height=0, width=0.35):
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

                # We hit something we're not ignoring!
                # Position us on the hit
                actor.set_actor_location(hit_result_info[4],
                                         sweep=False, teleport=True)

                # We're done now -- let our caller know we hit something facing this direction
                # and the distance to that object
                return True, hit_result_info[3]

    elif direction == "right" or direction == "left":
        # 1 == right, -1 == left
        direction = 1 if direction == "left" else -1

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


def get_selected_actors():
    """ return: obj List unreal.Actor : The selected actors in the world """
    return unreal.EditorLevelLibrary.get_selected_level_actors()


def point_actor_down(actor):
    # Reset actor rotation; which points down by default
    actor.set_actor_rotation(unreal.Rotator(0,-90,0), True)


def main():

    script_path = sys.argv.pop(0)
    if len(sys.argv) == 0:
        return

    if sys.argv[0] == "*" or sys.argv[0].lower() == "all":
        selected_actors = unreal.EditorLevelLibrary.get_all_level_actors()
    else:
        selected_actors = list()
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
                    for arg in sys.argv:
                        if mesh_name.startswith(arg):
                            selected_actors.append(actor)
                            break
    
    unreal.EditorLevelLibrary.set_selected_level_actors(selected_actors)

main()
