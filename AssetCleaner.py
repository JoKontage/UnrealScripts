"""
##########################################

       d8888                        888    .d8888b. 888                                        
      d88888                        888   d88P  Y88b888                                        
     d88P888                        888   888    888888                                        
    d88P 888.d8888b .d8888b  .d88b. 888888888       888 .d88b.  8888b. 88888b.  .d88b. 888d888 
   d88P  88888K     88K     d8P  Y8b888   888       888d8P  Y8b    "88b888 "88bd8P  Y8b888P"   
  d88P   888"Y8888b."Y8888b.88888888888   888    88888888888888.d888888888  88888888888888     
 d8888888888     X88     X88Y8b.    Y88b. Y88b  d88P888Y8b.    888  888888  888Y8b.    888     
d88P     888 88888P' 88888P' "Y8888  "Y888 "Y8888P" 888 "Y8888 "Y888888888  888 "Y8888 888     
                                                                                               
Wipe your mod's (unused) assets.
Saves package size and sanity.

Requires the "Python Editor Scripting" plugin to be enabled in UE4.
To run:

0. Right click your mod's folder, click "Audit Assets", click "View Options" -> "Export to CSV" (save as "Report.csv" in your Downloads folder)
1. Open the "Output Log"
2. Switch to "Python" mode
3. Enter the full path to this script and hit the Enter key
4. Select your mod from the list of mods
5. Highlight all assets you'd like to remove
6. Press "Remove Selected Assets" and be prepared to wait a looooong time (depending on the total # assets to remove)

##########################################
"""

from Tkinter import *
import tkFileDialog as fd
import tkMessageBox as messagebox
import ntpath
import posixpath
import csv
import unreal
import atexit
import json
import os
import traceback
import atexit
from glob import glob
from copy import copy

string = unreal.StringLibrary.conv_name_to_string
asset_lib = unreal.EditorAssetLibrary()
asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
level_lib = unreal.EditorLevelLibrary()
asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
editor_subsystem = unreal.AssetEditorSubsystem()

# Massive help from @mechamogera from Ricoh:
# https://qiita-com.translate.goog/mechamogera/items/87e2d52d9bf800c04c34


DEFAULT_REPORT_NAME = "Report.csv"


# Credit <3: https://its401.com/article/weixin_39874202/106600558
def slate_deco(func):
    def wrapper(self, single=True, *args, **kwargs):
        if single:
            for win in QtWidgets.QApplication.topLevelWidgets():
                if win is self:
                    continue
                elif self.__class__.__name__ in str(type(win)):
                    win.deleteLater()
                    win.close()
        # NOTE https://forums.unrealengine.com/unreal-engine/unreal-studio/1526501
        unreal.parent_external_window_to_slate(self.winId())
        return func(self, *args, **kwargs)
    return wrapper


class Assets:

    # Exclude assets in these paths
    exclusions = [
        "/engine/",
        "/script/",
        "/game/",
        "/content/",
        "/niagara/"
    ]

    # Specifically include files in these
    # paths (overturns exclusions)
    inclusions = [
        "/content/brushify"
    ]

    def __init__(self, mod_path=None, max_depth=10, skip_exclusions=True, skip_internal_assets=True, exclusions=None, inclusions=None):
        if mod_path:
            self.set_mod_path(mod_path)
        else:
            self.mod_path = None
            self.maps_dir = None
        self.max_depth = max_depth
        self.skip_exclusions = skip_exclusions
        self.skip_internal_assets = skip_internal_assets
        if exclusions:
            self.exclusions += [e.lower() for e in exclusions]
        if inclusions:
            self.inclusions += [i.lower() for i in inclusions]
        self.dependencies = dict()

    def set_mod_path(self, mod_path):
        self.mod_path = str("/" + mod_path + "/").replace("//", "/")
        self.maps_dir = "{}/Maps/".format(mod_path).replace("//", "/")

    def find_assets(self):

        # Discover default Downloads dir where report should be stored
        documents_dir = unreal.SystemLibrary.get_platform_user_dir()
        downloads_dir = documents_dir.replace("Documents", "Downloads")

        # Ask user to select the file if it doesn't exist as DEFAULT_REPORT_NAME
        report_file_path = ntpath.join(downloads_dir, DEFAULT_REPORT_NAME)
        if not ntpath.isfile(report_file_path):
            report_file_path = fd.askopenfilename(
                title="Please select your AssetManager report.",
                initialdir=downloads_dir,
                filetypes=(
                    ('AssetManager Report', 'Report.csv'),
                    ('All files', '*.*')
                )
            )

        unused_assets = set()
        used_assets = set()
        with open(report_file_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                asset_path = posixpath.join(row["Path"], row["Name"])
                if int(row["TotalUsage"]) > 0:
                    used_assets.add(asset_path)
                else:
                    unused_assets.add(asset_path)

        # Store these asset paths (replace any existing paths stored)
        self.used = used_assets
        self.unused = unused_assets

        # Return used and unused asset paths to caller
        return self.used, self.unused

    def remove(self, assets):
        asset_lib = unreal.EditorAssetLibrary()

        # Remove these assets from our Unreal project
        current_asset = ""
        with unreal.ScopedSlowTask(len(assets), current_asset) as task:
            task.make_dialog(True)
            for asset in assets:
                current_asset = asset
                asset_lib.delete_asset(asset)
                if task.should_cancel():
                    break
                task.enter_progress_frame(1, current_asset)

    def add(self, dependency_dict, dependency_path, used_by):
        # Add this asset to the list if we specified we wanted to add it,
        # or it's not an asset internal to the project
        if not self.skip_internal_assets or not dependency_path.lower().startswith(self.mod_path.lower()):
            if dependency_path not in dependency_dict:
                dependency_dict[dependency_path] = {}
            if used_by not in dependency_dict[dependency_path]:
                dependency_dict[dependency_path][used_by] = 0
            dependency_dict[dependency_path][used_by] += 1

    def get_list_dependencies(self, asset_data, depth=0):

        # Return if we're past the max_depth specified
        if depth > self.max_depth:
            return None

        asset_package_name = asset_data.get_editor_property("package_name")
        option = unreal.AssetRegistryDependencyOptions()
        dependencies = asset_registry.get_dependencies(asset_package_name, option)
        dependency_dict = {}
        unused_assets = set()

        if dependencies:

            for dependency in dependencies:

                dependency_path = string(dependency)

                # Skip any excluded package paths
                if self.skip_exclusions:
                    if not dependency_path.lower().startswith(tuple(self.inclusions)) \
                        and dependency_path.lower().startswith(tuple(self.exclusions)):
                        continue

                try:
                    dependency_asset = unreal.EditorAssetLibrary.find_asset_data(dependency)

                    # Attempt to add this asset to our dict
                    self.add(dependency_dict, dependency_path, used_by=string(asset_package_name))

                    # Get asset deps
                    dep_list, unused_deps = self.get_list_dependencies(dependency_asset, depth + 1)

                    # Add unused deps to unused_assets
                    unused_assets.update(unused_deps)

                    # If there are no deps for our current mod path,
                    # add to unused assets.
                    # dep_list = asset_lib.find_package_referencers_for_asset(dependency_asset)
                    if not dep_list or not [x for x in dep_list if self.mod_path in x]:
                        unused_assets.add(dependency_path)
                        continue

                    # Add all valid asset deps
                    for dep in dep_list:
                        if not dep:
                            continue
                        self.add(dependency_dict, string(dep), used_by=dependency_path)

                except:
                    pass

        return dependency_dict, unused_assets

    def get_map_assets(self):
        dependency_dict = {}
        # if level_lib.load_level(self.maps_dir + "/" + self.mod_path.strip("/")):
        components = level_lib.get_all_level_actors_components()
        for component in components:
            asset_paths = component.get_editor_property("asset_user_data")
            print(asset_paths)
            for asset_path in asset_paths:
                try:
                    asset_data = asset_lib.find_asset_data(asset_path)
                except Exception:
                    print(traceback.format_exc())
                for k, v in self.get_list_dependencies(asset_data).items():
                    for kk, vv in v.items():
                        dependency_dict[k][kk] += vv
        return dependency_dict

    def get_package_assets(self):
        dependency_dict = {}

        # Get all assets in the selected mod path
        assets = asset_registry.get_assets_by_path(
            self.mod_path.rstrip("/"),
            recursive=True,
            include_only_on_disk_assets=False)
        if not assets:
            return {}

        # Create scoped dialog in UE4 to let the user know we're doing stuff
        with unreal.ScopedSlowTask(len(assets), "Retrieving asset dependencies ...") as task:
            task.make_dialog(True)

            # Iterate over assets, getting the dependencies of each
            for asset in assets:

                used, _ = self.get_list_dependencies(asset)
                for k, v in used.items():
                    for kk, vv in v.items():
                        if not k in dependency_dict:
                            dependency_dict[k] = {}
                        if not kk in dependency_dict[k]:
                            dependency_dict[k][kk] = 0
                        dependency_dict[k][kk] += vv

                # Allow users to cancel
                if task.should_cancel():
                    break

                # Progress our task progress by 1
                task.enter_progress_frame(1, asset.get_full_name())

        self.dependencies = dependency_dict

        # Return a dictionary of dependency:usages
        return dependency_dict

    def get_package_references(self, package_path):
        dependency_dict = {}
        assets = asset_registry.get_assets_by_path(
            package_path,
            recursive=True,
            include_only_on_disk_assets=False)
        print("[*] Total assets to check: {}".format(len(assets)))
        for asset_data in assets:
            used_assets, unused_assets = self.get_list_dependencies(asset_data)
            for k, v in used_assets.items():
                for kk, vv in v.items():
                    #if not self.mod_path.lower() in kk.lower():
                    #    continue
                    if not k in dependency_dict:
                        dependency_dict[k] = {}
                    if not kk in dependency_dict[k]:
                        dependency_dict[k][kk] = 0
                    dependency_dict[k][kk] += vv
        return dependency_dict, unused_assets

    def get_unused_assets(self, package_path):
        assets = asset_registry.get_assets_by_path(
            package_path,
            recursive=True,
            include_only_on_disk_assets=False)
        print("[*] Total assets to check: {}".format(len(assets)))
        unused_assets = set()
        for asset_data in assets:
            _, unused = self.get_list_dependencies(asset_data)
            unused_assets.update(unused)
        return unused_assets

    def get_mod_paths(self):
        project_root_dir = unreal.SystemLibrary.get_project_directory()
        mods_dir = os.path.join(project_root_dir, "Mods")
        mod_directories = set()
        def convert_to_sandbox_path(p):
            return p.replace(mods_dir, "").replace("\\", "/")
        for mod_dir in glob(os.path.join(mods_dir, "*")):
            if os.path.isdir(mod_dir):
                mod_directories.add(convert_to_sandbox_path(ntpath.join(mods_dir, mod_dir)))
        return sorted(list(mod_directories))


class CustomToplevel(Toplevel):

    def __init__(self, parent, root, *args, **kwargs):
        Toplevel.__init__(self, parent, *args, **kwargs)
        self.root = root
        self.attributes('-topmost', 'true')

    def destroy(self):
        self.root.focus_set()
        Toplevel.destroy(self)


class ScrollableFrame(Frame):
    def __init__(self, parent, *args, **kwargs):
        Frame.__init__(self, parent, *args, **kwargs)
        canvas = Canvas(self)
        scrollbar = Scrollbar(self, orient="vertical", command=canvas.yview)
        self.scrollable_frame = Frame(canvas)
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )
        Label(self.scrollable_frame, text=" "*500).pack(expand=False, fill="x")
        self.scrollable_frame.pack(expand=True, fill="both")
        self.pack(expand=True, fill="both")
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=LEFT, fill="both", expand=True)
        scrollbar.pack(side=RIGHT, fill="y")


class FancyTextbox(Text):

    def __init__(self, parent, app, *args, **kwargs):
        Text.__init__(self, parent, *args, **kwargs)
        self.app = app
        self.popup_menu = Menu(self, tearoff=0)
        self.popup_menu.add_command(label="Copy All",
                                    command=self.copy_all)
        self.popup_menu.add_command(label="Refresh",
                                    command=self.refresh)
        self.bind("<Button-3>", self.popup) # Button-2 on Aqua

    def popup(self, event):
        try:
            self.popup_menu.tk_popup(event.x_root, event.y_root, 0)
        finally:
            self.popup_menu.grab_release()

    def copy_all(self):
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(self.get(1.0, END))

    def refresh(self):
        self.selection_set(0, END)


class DependencyList(Label):

    def __init__(self, parent, app, referencers, *args, **kwargs):
        Label.__init__(self, parent, *args, **kwargs)
        self.app = app
        self.listbox = Listbox(parent, selectmode="extended")
        if "font" not in kwargs:
            self.listbox.config(font=self.app.main_font)
        def on_right_click(event):
            self.listbox.selection_clear(0, END)
        self.listbox.bind("<Button-3><ButtonRelease-3>", on_right_click)
        # self.listbox.bind("<<ListboxSelect>>", )
        self.add_referencers(referencers)

    def add_referencers(self, referencers):
        # Add referencers
        for asset_path, times_referencd in referencers.items():
            self.listbox.insert(END, asset_path)

    def get_selected(self):
        return [self.listbox.get(i) for i in self.listbox.curselection()]

    def select_all(self):
        self.listbox.select_set(0, END)


class App:

    def __init__(self):

        # Get asset data
        self.assets = Assets()

        # Create root window
        self.title = "AssetCleaner"
        self.root = Tk()
        self.root.title(self.title)
        self.root.geometry("800x800")
        self.main_font = ("Helvatical bold", 8)

        self.setup_filter()
        self.setup_asset_list()
        self.setup_menu()

        # Add file open button
        self.btn = Button(self.root, text="Remove Selected Assets", command=self.remove_selected)
        self.btn.config(font=self.main_font)
        self.btn.pack(expand=False, fill="x")

        # Setup tick to handle Unreal ticks to update the UI
        self.tick_handle = None
        self.tick_time = 0
        self.tick_handle = unreal.register_slate_post_tick_callback(self.tick)

        # Ensure we tell Unreal know we're exiting and want to
        # unregister from the Slate tick function
        atexit.register(self.unregister_tick)

    def tick(self, delta_seconds):
        self.tick_time += delta_seconds
        if not self.running:
            unreal.unregister_slate_post_tick_callback(self.tick_handle)
            return
        # Only tick ~60 FPS
        if self.tick_time > 0.016:
            try:
                self.root.update_idletasks()
                self.root.update()
            except Exception:
                unreal.unregister_slate_post_tick_callback(self.tick_handle)
            self.tick_time = 0

    # Tell the Unreal Editor we're no longer handling ticks
    def unregister_tick():
        self.running = False
        # unreal.unregister_slate_post_tick_callback(self.tick_handle)

    def run(self):
        self.find_assets()
        self.running = True
        if not self.assets.mod_path:
            self.display_mod_path_selection()

    def on_filter_text_changed(self, string_var):
        if not "last_show_command" in dir(self):
            self.last_show_command = self.show_unused
        self.last_show_command(string_var)

    def show_dependencies(self):
        if not self.assets.dependencies or refresh:
            self.assets.dependencies = self.assets.get_package_assets()
        self.display_dependencies_box()

    def show_used(self, asset_filter=None):
        self.show_assets(self.assets.used, asset_filter)
        self.last_show_command = self.show_used

    def show_unused(self, asset_filter=None):
        self.show_assets(self.assets.unused, asset_filter)
        self.last_show_command = self.show_unused

    def show_all(self, asset_filter=None):
        self.show_assets(self.assets.used.union(self.assets.unused), asset_filter)
        self.last_show_command = self.show_all

    def show_assets(self, asset_types, asset_filter=None):
        self.asset_list.delete(0, END)
        if asset_filter:
            asset_filter = asset_filter.get()
        for asset in asset_types:
            if asset_filter:
                if asset_filter in asset:
                    self.asset_list.insert(END, asset)
            else:
                self.asset_list.insert(END, asset)

    def setup_filter(self):
        self.filter_text = StringVar()
        self.filter_text.trace("w", lambda name, index, mode, sv=self.filter_text: self.on_filter_text_changed(sv))
        self.filter = Entry(self.root, textvariable=self.filter_text, exportselection=0)
        self.filter.pack(expand=False, fill="x")

    def setup_menu(self):

        menubar = Menu(self.root)
        actions = Menu(menubar, tearoff=1)
        actions.add_command(label="Show All", command=self.show_all)
        actions.add_command(label="Show Only Used", command=self.show_used)
        actions.add_command(label="Show Only Unused", command=self.show_unused)
        actions.add_command(label="Show Dependencies", command=self.show_dependencies)
        actions.add_command(label="Remove Selected", command=self.remove_selected)
        actions.add_command(label="Remove All Listed", command=self.remove_listed)
        actions.add_separator()
        actions.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="Actions", menu=actions)

        edit_menu = Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Undo", accelerator="Ctrl+Z")
        edit_menu.add_separator()
        edit_menu.add_command(label="Cut", command=lambda: self.asset_list.event_generate("<<Cut>>"), accelerator="Ctrl+X")
        edit_menu.add_command(label="Copy", command=lambda: self.asset_list.event_generate("<<Copy>>"), accelerator="Ctrl+C")
        edit_menu.add_command(label="Paste", command=lambda: self.asset_list.event_generate("<<Paste>>"), accelerator="Ctrl+V")
        edit_menu.add_separator()
        edit_menu.add_command(label="Select All", command=lambda: self.asset_list.event_generate("<Control-a>"), accelerator="Ctrl+A")
        edit_menu.add_command(label="Select None", command=lambda: self.asset_list.event_generate("<Control-d>"), accelerator="Ctrl+D")
        menubar.add_cascade(label="Edit", menu=edit_menu)

        help = Menu(menubar, tearoff=0)
        def show_about_box():
            messagebox.showinfo(self.title, "Some message here ...")
        help.add_command(label="About", command=show_about_box)
        menubar.add_cascade(label="Help", menu=help)

        # Display of menu bar in the app
        self.menubar = menubar
        self.root.config(menu=menubar)

    def setup_asset_list(self):
        self.scrollbar = Scrollbar(self.root)
        self.scrollbar.pack(side=RIGHT, fill=Y)

        # Add text area
        """
        self.text = Text(self.root, height=8)
        self.text.config(font=self.main_font)
        self.text.pack(expand=True, fill="both")
        """
        def on_right_click(event):
            self.asset_list.selection_clear(0, END)
            #self.asset_list.selection_set(self.asset_list.nearest(event.y))
            #self.asset_list.activate(self.asset_list.nearest(event.y))
        def on_copy(event):
            self.root.clipboard_clear()
            for index in self.asset_list.curselection():
                self.root.clipboard_append(self.asset_list.get(index) + "\n")
        def on_cut(event):
            on_copy(event)
            for index in self.asset_list.curselection()[::-1]:
                self.asset_list.delete(index)
        def on_select_all(event):
            # Select start to end
            self.asset_list.select_set(0, END)
        def on_select_none(event):
            self.asset_list.selection_clear(0, END)

        self.asset_list = Listbox(self.root, yscrollcommand=self.scrollbar.set, selectmode="extended")
        self.asset_list.config(font=self.main_font)
        self.asset_list.bind("<Button-3><ButtonRelease-3>", on_right_click)
        # self.asset_list.bind("<<ListboxSelect>>", )
        self.asset_list.bind("<<Copy>>", on_copy)
        self.asset_list.bind("<<Cut>>", on_cut)
        self.asset_list.bind("<Control-a>", on_select_all)
        self.asset_list.bind("<Control-d>", on_select_none)
        self.asset_list.pack(expand=True, fill="both")
        self.scrollbar.config(command=self.asset_list.yview)

    def find_assets(self, asset_filter=None):
        self.asset_list.delete(0, END)
        _, unused_assets = self.assets.find_assets()
        for asset in unused_assets:
            if asset_filter:
                if asset_filter in asset:
                    self.asset_list.insert(END, asset)
            else:
                self.asset_list.insert(END, asset)

        # self.text.insert("1.0", "\n".join(list(unused_assets)))
        # self.text["state"] = "disabled"
        # dirr = fd.askdirectory(initialdir=downloads_dir)

    def remove_listed(self):
        # Get all assets listed in the asset_list
        listed_assets = set()
        for index in range(0, self.asset_list.size()):
            listed_assets.add(self.asset_list.get(index))
        print(listed_assets)
        self.assets.remove(listed_assets)
        exit(0)

    def remove_selected(self):
        # Get assets selected in the asset_list
        selected_assets = set()
        for index in self.asset_list.curselection():
            selected_assets.add(self.asset_list.get(index))
        print(selected_assets)
        self.assets.remove(selected_assets)
        exit(0)

    def display_data_grid(self, data, title="Data", geometry="750x250"):
        popup_window = CustomToplevel(self.root, self.root)
        popup_window.geometry(geometry)
        popup_window.title(title)

        # Ensure data is a list (should be a list of dicts)
        if not isinstance(data, list):
            if not isinstance(data, dict):
                data = {"NoHeader": data}
            data = [data]

        # Get IDs for all columns in dict
        columns = data[0].keys()
        rows = len(data)

        # Display all col/rows
        for r in range(rows):
            for c in range(len(columns)):
                if r == 0:
                    Entry(popup_window, text=columns[c], borderwidth=1).grid(row=r, column=c)
                else:
                    Entry(popup_window, text=data[r][columns[c]], borderwidth=1).grid(row=r, column=c)

        # Grab focus
        self.root.focus_set()
        popup_window.focus_set()

    def display_text_box(self, data, title="Text", geometry="640x420"):
        popup_window = CustomToplevel(self.root, self.root)
        popup_window.geometry(geometry)
        popup_window.title(title)

        scrollbar = Scrollbar(popup_window)
        scrollbar.pack(side=RIGHT, fill=Y)
        textbox = FancyTextbox(popup_window, self.root)
        textbox.config(font=self.main_font)
        textbox.pack(expand=True, fill="both")
        scrollbar.config(command=textbox.yview)

        # Ensure data is a list (should be a list of dicts)
        if isinstance(data, (list, dict, set)):
            if isinstance(data, set):
                data = list(data)
            textbox.insert(END, json.dumps(data, indent=2))
        else:
            textbox.insert(END, data)

        # Grab focus
        self.root.focus_set()
        textbox.focus_set()

    #Define a function to open the Popup Dialogue
    def display_dependencies_box(self):
        dependency_lists = list()
        dependency_selection_window = CustomToplevel(self.root, self.root)
        dependency_selection_window.geometry("420x640")
        dependency_selection_window.resizable(height=True, width=None)

        def on_select_all(event):
            # Select start to end
            for dl in dependency_lists:
                dl.listbox.select_set(0, END)
        def on_select_none(event):
            for dl in dependency_lists:
                dl.listbox.selection_clear(0, END)
        dependency_selection_window.bind("<Control-a>", on_select_all)
        dependency_selection_window.bind("<Control-d>", on_select_none)

        frame = Frame(dependency_selection_window)
        canvas = Canvas(frame)
        scrollbar = Scrollbar(frame, orient="vertical", command=canvas.yview)
        frame.scrollable_frame = Frame(canvas)
        frame.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )

        def on_open_selected_assets():
            selected_assets = [a for dl in dependency_lists for a in dl.get_selected()]
            if len(selected_assets) > 0:
                assets = list()
                for selected_asset in selected_assets:
                    assets.append(unreal.load_asset(selected_asset))
                editor_subsystem.open_editor_for_assets(assets)
                self.dependency_selection_window.destroy()
                self.dependency_selection_window.update()
            else:
                messagebox.showinfo("ERROR", "Please select a mod path to continue ...")

        # Add mod paths to selection window
        for dependency, referencers in self.assets.dependencies.items():
            d = DependencyList(
                frame.scrollable_frame, self, referencers, text=dependency,
                wraplength=132, justify="left"
            )
            dependency_lists.append(d)
            d.pack(expand=False, side="left", fill="x")
            d.listbox.pack(expand=True, fill="x")

        #frame.scrollable_frame.pack(expand=False, fill="x")
        #frame.pack(expand=True, fill="both")

        Label(frame.scrollable_frame, text=" "*132).pack(expand=True, fill="x")
        frame.scrollable_frame.pack(expand=True, fill="both")
        frame.pack(expand=True, fill="both")
        canvas.create_window((0, 0), window=frame.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=LEFT, fill="both", expand=True)
        scrollbar.pack(side=RIGHT, fill="y")

        # Add selection button
        btn = Button(dependency_selection_window, text="Open Selected", command=on_open_selected_assets)
        btn.config(font=self.main_font)
        btn.pack(expand=False, fill="x")

        #Create a Button Widget in the Toplevel Window
        #button= Button(top, text="Ok", command=lambda:close_win(top))
        #button.pack(pady=5, side= TOP)

    def old_di(self):
        dependency_selection_window = CustomToplevel(self.root, self.root)
        dependency_selection_window.geometry("420x420")
        frame = ScrollableFrame(dependency_selection_window)
        """
        for i in range(50):
            l = Label(frame.scrollable_frame, text="Sample scrolling label")
            l.pack(expand=True, fill="x")
        """
        # Pack the scrollable frame

        dependency_lists = list()
        def on_open_selected_assets():
            selected_assets = [a for dl in dependency_lists for a in dl.get_selected()]
            if len(selected_assets) > 0:
                assets = list()
                for selected_asset in selected_assets:
                    assets.append(unreal.load_asset(selected_asset))
                asset_tools.open_editor_for_assets(assets)
                self.dependency_selection_window.destroy()
                self.dependency_selection_window.update()
            else:
                messagebox.showinfo("ERROR", "Please select a mod path to continue ...")

        # Add mod paths to selection window
        for dependency, referencers in self.assets.dependencies.items():
            dependency_lists.append(
                DependencyList(
                    frame.scrollable_frame, self, referencers, text=dependency,
                    wraplength=132, justify="left"
                ))

        #frame.scrollable_frame.pack(expand=False, fill="x")
        #frame.pack(expand=True, fill="both")

        # Add selection button
        btn = Button(dependency_selection_window, text="Open Selected", command=on_open_selected_assets)
        btn.config(font=self.main_font)
        btn.pack(expand=False, fill="x")

        #Create a Button Widget in the Toplevel Window
        #button= Button(top, text="Ok", command=lambda:close_win(top))
        #button.pack(pady=5, side= TOP)


    #Define a function to open the Popup Dialogue
    def display_mod_path_selection(self):

        #Create a Toplevel window
        self.mod_path_selection_window = CustomToplevel(self.root, self.root)
        self.mod_path_selection_window.geometry("420x420")

        def on_use_selected_mod_path(event=None):
            if len(mod_path_list.curselection()) > 0:
                selected_mod_path = mod_path_list.get(mod_path_list.curselection()[0])
                self.assets.set_mod_path(selected_mod_path)
                self.mod_path_selection_window.destroy()
                self.mod_path_selection_window.update()
                # self.show_dependencies()
            else:
                messagebox.showinfo("ERROR", "Please select a mod path to continue ...")

        scrollbar = Scrollbar(self.mod_path_selection_window)
        scrollbar.pack(side=RIGHT, fill=Y)
        mod_path_list = Listbox(self.mod_path_selection_window, yscrollcommand=scrollbar.set, selectmode="single")
        mod_path_list.config(font=self.main_font)
        mod_path_list.bind("<Double-Button-1>", on_use_selected_mod_path)
        mod_path_list.pack(expand=True, fill="both")
        scrollbar.config(command=mod_path_list.yview)

        # Add mod paths to selection window
        for mod_path in self.assets.get_mod_paths():
            mod_path_list.insert(END, mod_path)

        # Add selection button
        btn = Button(self.mod_path_selection_window, text="Use Selected Mod Path", command=on_use_selected_mod_path)
        btn.config(font=self.main_font)
        btn.pack(expand=False, fill="x")

        # Get focus
        self.mod_path_selection_window.focus_set()


def main():
    app = App()
    try:
        app.run()
    except Exception:
        app.running = False
        print(traceback.format_exc())

if __name__ == "__main__":
    main()
