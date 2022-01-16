# Replace words in assets
import unreal
import sys

HELP_TEXT = '''

This is an Unreal Python API script which renames assets which contain a specific word,
replacing that word with the word we specify (or with nothing if nothing is specified)

Example Usage:

    "C:/Modding/Unreal Scripts/replace-words-in-assets.py" /Frontier1944/FactionsREDONE/PlayerClasses/Axis Insurgent Axis

Explaination:

    "C:/Modding/Unreal Scripts/replace-words-in-assets.py": path to the script, surrounded with quotes ("") because it contains a space

    /Frontier1944/FactionsREDONE/PlayerClasses/Axis:        path to directory of assets to search

    Insurgent:                                              word to replace

    Axis:                                                   word to use for the replacement

'''

def main():

    # Get script title (pull from our arguments list: sys.argv)
    script_title = sys.argv.pop(0)

    # If no arguments were provided, exit
    if len(sys.argv) < 2:
        print("-------------------------------")
        print("[!] Missing arguments!")
        print("Usage: {} <path/to/directory/to/search> <word_to_replace> [replacement_word".format(script_title))
        print(HELP_TEXT)
        print("-------------------------------")
        return

    # Create a new variable called "directory_path"
    # using the first argument passed in
    directory_path = sys.argv[0].replace("/Content", "")
    word_to_replace = sys.argv[1]

    # If we specified a replacement word,
    # use it as our replacement word --
    # otherwise use nothing as the replacement word
    if len(sys.argv) >= 3:
        replacement_word = sys.argv[2]
    else:
        replacement_word = ""

    # Perform the below operations in a ScopedTransaction, which
    # allows us to undo changes afterwards
    with unreal.ScopedEditorTransaction("Rename Assets") as trans:

        # Find all assets in the target directory (and lower; recursive)
        # and replace the specified word with our specific replacement word
        for asset_path in unreal.EditorAssetLibrary.list_assets(directory_path):

            # Get asset data
            asset_data = unreal.EditorAssetLibrary.find_asset_data(asset_path)

            # Skip this asset if our word is not in it's name
            asset_name = str(asset_data.get_editor_property("asset_name"))
            if word_to_replace not in asset_name:
                continue
            
            # Get the asset's name with our replacement word
            replacement_asset_name = asset_name.replace(word_to_replace, replacement_word)
            asset_path_with_replacement_word = asset_path.replace(asset_name, replacement_asset_name)

            # Add this asset to our list of assets to rename
            unreal.EditorAssetLibrary.rename_asset(asset_path, asset_path_with_replacement_word)

            # Automatically save the renamed asset
            # unreal.EditorAssetLibrary.save_asset(asset_path)


# Start the main function!
main()