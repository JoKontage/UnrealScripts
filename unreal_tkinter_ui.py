from Tkinter import *
import unreal

class UnrealApp:

    def __init__(self):
        self.root = Tk()

        # Example text area
        textarea = Text(self.root)
        textarea.pack(expand=True, fill="both")
        textarea.insert(END, "Heya!")

    def run(max_tick_time=0.16):

        # Don't use this; it'll block the UE4's Slate UI ticks
        # root.mainloop()

        # Instead, do the below:
        self.tick_handle = None
        self.tick_time = 0

        def tick(delta_seconds):
            self.tick_time += delta_seconds
            # TODO: Use FPS instead of a hardcoded number to delay ticks
            if self.tick_time > max_tick_time:
                try:
                    self.root.update_idletasks()
                    self.root.update()
                except Exception:
                    pass
                self.tick_time = 0

        # Setup our app to handle Unreal ticks to update the UI
        self.tick_handle = unreal.register_slate_post_tick_callback(tick)


if __name__ == "__main__":
    app = UnrealApp()
    app.run()
