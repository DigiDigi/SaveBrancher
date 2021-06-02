#!/bin/env python3

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import Gio
import cairo, math, os, shutil
import pickle, json, csv


# Everything refers to objects by id so they can be saved as json. Here we keep the references to the actual objects.
class Objects(object):
    nodes = {}


class Main(object):
    def __init__(self):
        self.node_id_list = []  # List of node ids (referencable in the Objects.nodes list)
        self.next_node_id = -1
        self.drawarea_size = []
        self.drawarea_extra = [0, 0]  # Extra amount of drawarea that is scrollable.
        self.window_size = [1280, 960]
        self.source_filepath = None  # This will be None while an sbr file is not accessed and source is not known.
        self.source_filename = None
        self.tree_filename = None
        self.tree_dirpath = None
        self.tree_filepath = None

    def new_node_id(self):  # New object IDs.
        self.next_node_id += 1
        return self.next_node_id

    def adjust_indices(self, index):  # Adjust indices of the objects after the one being removed.
        adjust_list = self.node_id_list[index + 1:]
        for node_id in adjust_list:
            Objects.nodes[node_id].render_index -= 1

    def bring_top(self, node_id):  # Bring an object to the front of the rendering order.
        self.adjust_indices(Objects.nodes[node_id].render_index)
        self.node_id_list.pop(Objects.nodes[node_id].render_index)    # Remove target object from rendering list.
        Objects.nodes[node_id].render_index = len(self.node_id_list)  # New rendering index at the end of the list.
        self.node_id_list.append(node_id)              # Add to the end of the list.

    def remove_object(self, node):  # Remove an object from the rendering list.
        self.adjust_indices(node.render_index)
        self.node_id_list.pop(node.render_index)
        del Objects.nodes[node.node_id]

    def add_object(self, node):  # Add an object to the rendering list.
        node.render_index = len(self.node_id_list)
        self.node_id_list.append(node.node_id)
        Objects.nodes[node.node_id] = node


main = Main()


# Prototype node object.
class Node(object):
    def __init__(self, text="default", pos=(0, 0)):
        self.super_node_id = None
        self.sub_node_ids = []
        self.text = text
        self.x = pos[0]
        self.y = pos[1]
        self.w = 20
        self.h = 20
        self.ext_width = 100    # Dimensions of box after padding with text.
        self.ext_height = 100
        self.text_width = 0     # Text string dimensions.
        self.text_height = 0
        self.text_x = 0
        self.text_y = 0
        self.render_index = None             # Index of this node element in main.node_id_list for rendering order.
        self.node_id = main.new_node_id()

    def add_subnode(self, node_id):  # Creates an edge from this node to a subnode; connecting the two.
        sub_node = Objects.nodes[node_id]
        if node_id not in self.sub_node_ids:
            if sub_node.super_node_id:
                sub_node.super_node_id.sub_node_ids.pop(sub_node.super_node_id.sub_node_ids.index(sub_node.node_id))
            self.sub_node_ids.append(sub_node.node_id)
            sub_node.super_node_id = self.node_id


class AppWindow(Gtk.ApplicationWindow):
    def __init__(self):
        Gtk.Window.__init__(self)

        self.flag_dragging = False
        self.grabbed_diff = [0, 0]  # Space between the position of a grabbed box and the cursor.

        self.grabbed_node_id = None
        self.selected_node_id = None
        self.selected_node_ids = []
        self.target_node_id = None  # Object targeted with right click.

        self.mod_ctrl = False
        self.mod_shift = False
        # Last mouse positions (usually after right clicking a space)
        self.last_m_x = 0
        self.last_m_y = 0

        self.set_icon_from_file('savebrancher.png')
        self.gladefile = "savebrancher.glade"
        self.builder = Gtk.Builder()                # Used to build gui objects from our glade file.
        self.builder.add_from_file(self.gladefile)  #
        self.builder.connect_signals(self)          # Connect the signals to our callbacks in this object.
        self.mainbox = self.builder.get_object("mainbox")
        self.mainbox.get_parent().remove(self.mainbox)  # Remove the window I have for previewing in Glade.
        self.add(self.mainbox)

        self.onloadbuffer = Gtk.TextBuffer()
        f = open('onloadscript.py', 'r')
        scriptlines = f.readlines()
        f.close()
        scriptlines = "".join(scriptlines)
        self.onloadbuffer.set_text(scriptlines)

        self.bars_hidden = False

        self.menubar1 = self.builder.get_object("menubar1")
        self.box1 = self.builder.get_object("box1")

        self.connect('check-resize', self.cb_windowresize)

        self.entry_rename = self.builder.get_object("entry_rename")
        self.dialog_rename = self.builder.get_object("dialog_rename")
        self.entry_newsave = self.builder.get_object("entry_newsave")
        self.dialog_newsave = self.builder.get_object("dialog_newsave")
        self.entry_appendsave = self.builder.get_object("entry_appendsave")
        self.dialog_appendsave = self.builder.get_object("dialog_appendsave")

        self.scrolledwindow = self.builder.get_object("scrolledwindow")
        self.widget_area = self.builder.get_object("widget_area")
        self.drawarea = self.builder.get_object("drawarea")
        self.drawarea.set_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.drawarea.connect('draw', self.cb_draw)
        self.eventbox = self.builder.get_object("eventbox")
        self.eventbox.connect('button-press-event', self.cb_click)
        self.eventbox.connect('button-release-event', self.cb_release)
        self.eventbox.connect('motion-notify-event', self.cb_motion)
        self.statusbar = self.builder.get_object("statusbar")

        self.menuitem_save = self.builder.get_object("menuitem_save")
        self.save_accelgroup = Gtk.AccelGroup()
        self.add_accel_group(self.save_accelgroup)
        self.menuitem_save.add_accelerator("activate", self.save_accelgroup, ord("S"), Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)

        self.widget_area.set_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.eventbox.set_events(Gdk.EventMask.BUTTON_PRESS_MASK)

        # Node menu when no node is selected.
        self.spacemenu = Gtk.Menu()
        self.sm_appendsave = Gtk.MenuItem(label=("Append new save"))
        self.spacemenu.append(self.sm_appendsave)
        self.sm_appendsave.connect('button-press-event', self.cb_appendsave)
        self.sm_appendsave.show()
        self.sm_newsave = Gtk.MenuItem(label=("Copy new save"))
        self.spacemenu.append(self.sm_newsave)
        self.sm_newsave.connect('button-press-event', self.cb_newsave)
        self.sm_newsave.show()

        # Node menu right-clicking a node.
        self.nodemenu = Gtk.Menu()
        self.nm_rename = Gtk.MenuItem(label=("Rename"))
        self.nodemenu.append(self.nm_rename)
        self.nm_rename.connect('button-press-event', self.cb_rename)
        self.nm_rename.show()
        self.nm_linksave = Gtk.MenuItem(label=("Link"))
        self.nodemenu.append(self.nm_linksave)
        self.nm_linksave.connect('button-press-event', self.cb_linksave)
        self.nm_linksave.show()
        self.nm_unlink = Gtk.MenuItem(label=("Unlink"))
        self.nodemenu.append(self.nm_unlink)
        self.nm_unlink.connect('button-press-event', self.cb_unlink)
        self.nm_unlink.show()
        self.nm_writesave = Gtk.MenuItem(label="Load save (Overwrite Slot)")
        self.nodemenu.append(self.nm_writesave)
        self.nm_writesave.connect('button-press-event', self.cb_writesave)
        self.nm_writesave.show()

        # CSS styling and settings >
        settings = Gtk.Settings.get_default()
        settings.props.gtk_button_images = True
        style_provider = Gtk.CssProvider()
        css = open('savebrancher.css', 'rb')
        css_data = css.read()
        css.close()
        style_provider.load_from_data(css_data)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        allocation = self.widget_area.get_allocation()
        w = allocation.width
        h = allocation.height
        main.drawarea_size = [w, h]

        self.default_window_size = self.get_size()

        # Displays selected save filename.
        self.statusbar1 = self.builder.get_object("statusbar1")
        self.context_id1 = self.statusbar1.get_context_id("status")
        self.statusbar1.push(self.context_id1, "...")
        # Displays tree directory path.
        #self.statusbar2 = self.builder.get_object("statusbar2")
        #self.context_id2 = self.statusbar2.get_context_id("status")
        #self.statusbar2.push(self.context_id2, "...")
        # Displays selected node ID. (For knowing which save to grab in the folder if you need to.)
        self.statusbar4 = self.builder.get_object("statusbar4")
        self.context_id4 = self.statusbar4.get_context_id("status")
        self.statusbar4.push(self.context_id4, "....")

        self.file_newsource = Gtk.FileChooserDialog(title="Select a source state/save.",
                                                    parent=None,
                                                    action=Gtk.FileChooserAction.OPEN)
        self.file_newsource.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        self.file_newsource.connect("response", self.cb_newsource_response)
        self.file_newsource.connect("delete-event", self.cb_delete_event)
        self.file_opentree = Gtk.FileChooserDialog(title="Select an existing tree file.",
                                                   parent=None,
                                                   action=Gtk.FileChooserAction.OPEN)
        self.file_opentree.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        self.file_opentree.connect("response", self.cb_opentree_response)
        self.file_opentree.connect("delete-event", self.cb_delete_event)
        self.dialog_onload = self.builder.get_object("dialog_onload")
        self.dialog_onload.connect("delete-event", self.cb_delete_event)
        self.button_onload_cancel = self.builder.get_object("button_onload_cancel")
        self.button_onload_confirm = self.builder.get_object("button_onload_confirm")
        self.textview_onload = self.builder.get_object("textview_onload")
        self.textview_onload.set_buffer(self.onloadbuffer)
        self.dialog_warncreate = Gtk.MessageDialog(parent=None,
                                                   flags=0,
                                                   message_type=Gtk.MessageType.INFO,
                                                   text="Create savetree from:")
        self.dialog_warncreate.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        self.dialog_warncreate.connect("response", self.cb_warncreate_response)
        self.dialog_warncreate.connect("delete-event", self.cb_delete_event)
        self.dialog_error = Gtk.MessageDialog(parent=None,
                                              flags=0,
                                              message_type=Gtk.MessageType.ERROR,
                                              text="Error.")
        self.dialog_error.add_buttons(Gtk.STOCK_OK, Gtk.ResponseType.OK)
        self.dialog_error.connect("response", self.cb_error_response)
        self.dialog_error.connect("delete-event", self.cb_delete_event)

    # Redraw drawarea.
    def redraw(self):
        self.drawarea.queue_draw_area(0,
                                      0,
                                      main.drawarea_size[0]+main.drawarea_extra[0],
                                      main.drawarea_size[1]+main.drawarea_extra[1])

    def clear_paths(self):
        main.source_filepath = None
        main.source_filename = None
        main.tree_filename = None
        main.tree_dirpath = None
        main.tree_filepath = None

    def save_sbr(self):
        # Save current window size for later restoration.
        main.window_size = self.get_size()[:]
        try:
            sbr_file = open(main.tree_filepath, 'wb')
            pickle.dump(main, sbr_file)
            sbr_file.close()
            self.set_title("SaveBrancher")
            return True
        except:
            # WIP: Could add error dialog here.
            return False
    def unsaved_changes(self):
        self.set_title("SaveBrancher(*)")
        self.menuitem_save.set_sensitive(True)

    # Open file selection for a new save source.
    def cb_newsource_show(self, widget):
        self.file_newsource.show()

    def cb_newsource_response(self, widget, response):
        if response == Gtk.ResponseType.OK:
            self.temp_source_filepath = self.file_newsource.get_filename()  # Get filepath of source save.
            self.file_newsource.hide()
            self.dialog_warncreate.format_secondary_text(main.source_filepath)
            self.dialog_warncreate.show()
        elif response == Gtk.ResponseType.CANCEL:
            self.file_newsource.hide()

    def cb_warncreate_response(self, widget, response):
        global main
        if response == Gtk.ResponseType.OK:
            main = Main()
            main.source_filepath = self.temp_source_filepath[:]
            main.source_filename = os.path.split(main.source_filepath)[-1]  # Get filename.
            main.tree_filename = main.source_filename + '.sbr'
            treepath = os.path.split(main.source_filepath)[:-1][0]
            main.tree_dirpath = os.path.join(treepath, main.source_filename) + ' SBR'
            main.tree_filepath = os.path.join(main.tree_dirpath, main.tree_filename)

            # Create savebrancher sub-directory for this source file.
            self.directory_exists = False
            try:
                os.makedirs(main.tree_dirpath)
                self.directory_exists = True
            except OSError:
                if not os.path.isdir(main.tree_dirpath):
                    # Could not create directory.
                    self.directory_exists = False
                else:
                    self.directory_exists = True
            if not self.directory_exists:
                self.clear_paths()
                self.dialog_error.set_property("text", "Couldn\'t create directory:")
                self.dialog_error.format_secondary_text(main.tree_dirpath)
                self.dialog_error.show()
                self.dialog_warncreate.hide()
                return

            else:
                # Directory was created successfully:
                pass

            # Create savebrancher file. (Main object containing all nodes/positions, window size)
            savesbr = self.save_sbr()

            if not savesbr:
                self.clear_paths()
                self.dialog_error.set_property("text", "Couldn\'t create file:")
                self.dialog_error.format_secondary_text(main.tree_filepath)
                self.dialog_error.show()
                self.dialog_warncreate.hide()
                self.statusbar1.push(self.context_id4, "...")
                return

            self.statusbar1.push(self.context_id4, main.source_filepath)
            self.dialog_warncreate.hide()

        elif response == Gtk.ResponseType.CANCEL:
            self.dialog_warncreate.hide()

    def cb_error_response(self, widget, response):
        if response == Gtk.ResponseType.OK:
            self.dialog_error.hide()

    # Open file selection for an exiting tree file.
    def cb_opentree_show(self, widget):
        self.file_opentree.show()

    def cb_opentree_response(self, widget, response):
        global main
        if response == Gtk.ResponseType.OK:
            openfn = self.file_opentree.get_filename()
            if openfn.split('.')[-1] == 'sbr':
                with open(openfn, 'rb') as sbrfile:
                    try:
                        oldmain = pickle.load(sbrfile, encoding='latin1')
                        print('Loading old-style SaveBrancher file.')
                        newmain = Main()
                        newmain.node_id_list = []
                        newmain.next_node_id = oldmain.next_obj_id
                        newmain.drawarea_size = oldmain.drawarea_size
                        newmain.drawarea_extra = oldmain.drawarea_extra
                        newmain.window_size = oldmain.window_size
                        newmain.source_filepath = oldmain.source_filepath
                        newmain.source_filename = oldmain.source_filename
                        newmain.tree_filename = oldmain.tree_filename
                        newmain.tree_dirpath = oldmain.tree_dirpath
                        newmain.tree_filepath = oldmain.tree_filepath
                        main.node_id_list = []
                        Objects.nodes = {}
                        main = newmain
                        for node in oldmain.obj_list:
                            # Convert old SaveBrancher attributes. (This destroys old edges.)
                            if hasattr(node, 'sub_edges'):  # super_edges will also exist in this case
                                del node.sub_edges
                                del node.super_edges
                            newnode = Node()
                            newnode.text = node.text
                            newnode.x = node.x
                            newnode.y = node.y
                            newnode.w = node.w
                            newnode.h = node.h
                            newnode.ext_width = node.ext_width
                            newnode.ext_height = node.ext_height
                            newnode.text_width = node.text_width
                            newnode.text_height = node.text_height
                            newnode.text_x = node.text_x
                            newnode.text_y = node.text_y
                            newnode.render_index = node.render_index
                            newnode.node_id = node.obj_id
                            main.add_object(newnode)
                    except (TypeError, pickle.UnpicklingError):
                        # This will be the default way.
                        # Having one update with the conversion on the off chance someone used this.
                        m = json.load(sbrfile)
                        main.__dict__ = m[:1][0]
                        nodes = m[1:]
                        main.node_id_list = []
                        Objects.nodes = {}
                        for n in nodes:
                            node = Node()
                            node.__dict__ = n
                            main.add_object(node)
                self.resize(main.window_size[0], main.window_size[1])
                self.drawarea.set_size_request(main.drawarea_size[0] + main.drawarea_extra[0],
                                               main.drawarea_size[1] + main.drawarea_extra[1])
                self.redraw()
                self.statusbar1.push(self.context_id4, main.source_filepath)
            else:
                pass

            self.file_opentree.hide()
        elif response == Gtk.ResponseType.CANCEL:
            self.file_opentree.hide()

    # Save node positions. Everything else is saved on action. ?: Seems a bit clunky though.
    def cb_menusave(self, widget):
        self.save_sbr()
        #self.menuitem_save.set_sensitive(False)

    def cb_quit(self, widget):
        # WIP: Do dialog if positions haven't been saved.
        self.destroy()

    def cb_delete_event(self, widget, event):
        # ?: Dialogs have a weird bug of partially destroying themselves when X'd or canceled out
        # This is an override for that behavior that instead hides the widget.
        widget.hide()
        return True

    # TextView (EventBox) is clicked.
    def cb_edit_click(self, widget, event):
        widget.get_window().set_cursor(Gdk.Cursor.new_from_name(self.get_display(), "row-resize"))
        widget.get_child().set_can_focus(True)
        widget.get_child().grab_focus()
        widget.get_child().set_can_focus(False)

    def cb_writesave(self, widget, data):
        fileprefix = main.source_filename + '.' + str(self.selected_node_id)
        nodefilepath = os.path.join(main.tree_dirpath, fileprefix)
        shutil.copy2(nodefilepath, main.source_filepath)
        print(nodefilepath, main.source_filepath)
        with open("onloadscript.py") as f:
            code = compile(f.read(), "onloadscript.py", 'exec')
            exec(code)

    def cb_linksave(self, widget, data):
        for node_id in self.selected_node_ids:
            if node_id is not self.target_node_id:
                Objects.nodes[node_id].add_subnode(self.target_node_id)
        self.target_node_id = None
        self.save_sbr()
        self.redraw()

    # Remove link to parent node.
    def cb_unlink(self, widget, data):
        target_node = Objects.nodes[self.target_node_id]
        if target_node.super_node_id:
            findex = Objects.nodes[target_node.super_node_id].sub_node_ids.index(self.target_node_id)
            Objects.nodes[target_node.super_node_id].sub_node_ids.pop(findex)
            target_node.super_node_id = None  # .
        self.save_sbr()
        self.redraw()

    def cb_rename(self, widget, data):
        if self.target_node_id:
            self.dialog_rename.show()

    def cb_onload(self, widget):
        # load the script.
        f = open('onloadscript.py', 'r')
        scriptlines = f.readlines()
        f.close()
        scriptlines = "".join(scriptlines)
        self.onloadbuffer.set_text(scriptlines)
        self.dialog_onload.show()

    def cb_onload_canceled(self, widget):
        self.dialog_onload.hide()

    def cb_onload_confirmed(self, widget):
        f = open('onloadscript.py', 'w')
        f.writelines(self.onloadbuffer.get_text(self.onloadbuffer.get_start_iter(), self.onloadbuffer.get_end_iter(), True))
        f.close()
        self.dialog_onload.hide()

    def cb_focus(self, widget, data):
        pass

    def cb_focus_in(self, widget, data):
        self.mod_ctrl = False
        self.mod_shift = False

    def cb_focus_out(self, widget, data):
        pass

    def cb_click(self, widget, event):
        # record last mouse positions.
        self.last_m_x = event.x
        self.last_m_y = event.y

        # TD: Iterating for all objects. Add bin detection instead.
        self.target_node_id = None
        foundnode = [False]
        for node_id in main.node_id_list:
            node = Objects.nodes[node_id]
            if event.x >= node.x and event.x < node.x+node.ext_width:
                if event.y >= node.y and event.y < node.y+node.ext_height:
                    foundnode[0] = True
                    if event.button == Gdk.BUTTON_PRIMARY:
                        if self.mod_ctrl:
                            if node.node_id in self.selected_node_ids:
                                sindex = self.selected_node_ids.index(node.node_id)
                                self.selected_node_ids.pop(sindex)
                            self.selected_node_ids.append(node.node_id)
                            self.selected_node_id = node.node_id
                        else:
                            self.selected_node_ids = [node.node_id]
                            self.selected_node_id = node.node_id


                        self.flag_dragging = True
                        self.grabbed_node_id = node.node_id
                        self.grabbed_diff = [event.x - node.x, event.y - node.y]
                    elif event.button == Gdk.BUTTON_SECONDARY:
                        self.selected_node_id = node.node_id
                        self.target_node_id = node.node_id
                        self.nodemenu.popup(None, None, None, None, event.button, event.time)
                    idstring = ''
                    for node_id in self.selected_node_ids:
                        idstring = idstring + str(node_id) + ', '
                    idstring = idstring[:-2]
                    self.statusbar4.push(self.context_id4, idstring)

        if foundnode[0] is False:
            self.grabbed_node_id = None
            self.target_node_id = None

            if event.button == Gdk.BUTTON_PRIMARY:
                self.selected_node_ids = []

            elif event.button == Gdk.BUTTON_SECONDARY:
                if main.source_filepath:
                    # Right-clicked on blank space: open space menu.
                    if len(self.selected_node_ids) > 0:
                        # Some amount of nodes are selected.
                        self.sm_appendsave.show()
                        self.sm_newsave.hide()
                        self.spacemenu.popup(None, None, None, None, event.button, event.time)
                    else:
                        # No nodes are selected.
                        self.sm_newsave.show()
                        self.sm_appendsave.hide()
                        self.spacemenu.popup(None, None, None, None, event.button, event.time)

            self.redraw()
        else:
            if len(self.selected_node_ids) > 0:
                main.bring_top(self.selected_node_ids[-1])
                self.redraw()
        self.eventbox.grab_focus()

    def cb_release(self, widget, event):
        self.flag_dragging = False
        self.grabbed_node_id = None
        self.grabbed_diff = [0, 0]

    def cb_motion(self, widget, event):
        if self.flag_dragging:

            gox = event.x - self.grabbed_diff[0]
            goy = event.y - self.grabbed_diff[1]
            new_posx = gox
            new_posy = goy
            if gox < 0:
                new_posx = 0
            if goy < 0:
                new_posy = 0

            # Expand drawarea right/lower dimension if a node nears that side.
            grabbed_object = Objects.nodes[self.grabbed_node_id]
            if gox + grabbed_object.ext_width >= main.drawarea_size[0] + main.drawarea_extra[0]:
                main.drawarea_extra[0] += 4
                self.drawarea.set_size_request(main.drawarea_size[0] + main.drawarea_extra[0],
                                               main.drawarea_size[1] + main.drawarea_extra[1])
            if goy + grabbed_object.ext_height >= main.drawarea_size[1] + main.drawarea_extra[1]:
                main.drawarea_extra[1] += 4
                self.drawarea.set_size_request(main.drawarea_size[0] + main.drawarea_extra[0],
                                               main.drawarea_size[1] + main.drawarea_extra[1])
            grabbed_object.x = new_posx
            grabbed_object.y = new_posy

            self.unsaved_changes()

            self.redraw()

    def cb_removenodes(self, widget):
        # WIP: Should have a warning dialog before deletion.
        if len(self.selected_node_ids) > 0:
            for node_id in self.selected_node_ids:
                node = Objects.nodes[node_id]
                for sub_node in node.sub_node_ids:
                    sub_node.super_node_id = None
                node.sub_node_ids = []
                nodefn = main.tree_filename[:-4] + '.' + str(node_id)
                nodefp = os.path.join(main.tree_dirpath, nodefn)
                os.remove(nodefp)
                main.remove_object(node)

            self.selected_node_ids = []
            self.grabbed_node_id = None
            self.target_node_id = None
            self.save_sbr()
            self.redraw()

    def cb_rename_confirmed(self, widget):
        self.target_node_id.text = self.entry_rename.get_text()
        self.entry_rename.set_text("")
        self.dialog_rename.hide()
        self.save_sbr()
        self.redraw()

    def cb_rename_canceled(self, widget):
        self.dialog_rename.hide()

    def cb_rename_keyrelease(self, widget, event):
        if event.keyval == Gdk.KEY_Return:  # !: Should probably also only do this only if Ok is highlighted.
            self.cb_rename_confirmed(widget)
        if event.keyval == Gdk.KEY_Escape:
            self.entry_rename.set_text("")
            self.dialog_rename.hide()

    def cb_appendsave(self, widget, data):
        if len(self.selected_node_ids) > 0:
            self.dialog_appendsave.show()
        else:
            if len(main.node_id_list) == 0:
                self.dialog_appendsave.show()
            else:
                self.dialog_appendsave.show()

    def cb_appendsave_confirmed(self, widget):

        # Copy source savefile to a node savefile.
        # WIP: Add error checking.
        fileprefix = main.source_filename + '.' + str(main.next_node_id + 1)
        savedest = os.path.join(main.tree_dirpath, fileprefix)
        shutil.copy2(main.source_filepath, savedest)

        newtext = self.entry_appendsave.get_text()
        nx = self.last_m_x
        ny = self.last_m_y
        node = Node(newtext, (nx, ny))
        main.add_object(node)

        # Push the node back into the draw area if its new position is outside.
        if nx < 0:
            nx = 0
        if ny < 0:
            ny = 0
        if nx + node.ext_width >= main.drawarea_size[0] + main.drawarea_extra[0]:
            nx = main.drawarea_size[0] - node.ext_width
        if ny + node.ext_height >= main.drawarea_size[1] + main.drawarea_extra[1]:
            ny = main.drawarea_size[1] - node.ext_height
        node.x = nx
        node.y = ny

        self.entry_appendsave.set_text("")
        self.dialog_appendsave.hide()
        for sn in self.selected_node_ids:
            Objects.nodes[sn].add_subnode(node.node_id)

        self.save_sbr()
        self.redraw()

    def cb_appendsave_canceled(self, widget):
        self.entry_appendsave.set_text("")
        self.dialog_appendsave.hide()

    def cb_appendsave_keyrelease(self, widget, event):
        if event.keyval == Gdk.KEY_Return:
            self.cb_appendsave_confirmed(widget)
        if event.keyval == Gdk.KEY_Escape:
            self.entry_appendsave.set_text("")
            self.dialog_appendsave.hide()

    def cb_newsave(self, widget, event):
        if len(self.selected_node_ids) > 0:
            self.dialog_newsave.show()
        else:
            if len(main.node_id_list) == 0:
                self.dialog_newsave.show()
            else:
                self.dialog_newsave.show()

    def cb_newsave_confirmed(self, widget):

        # Copy source savefile to a node savefile.
        # WIP: Add error checking.
        fileprefix = main.source_filename + '.' + str(main.next_node_id + 1)
        savedest = os.path.join(main.tree_dirpath, fileprefix)
        shutil.copy2(main.source_filepath, savedest)

        newtext = self.entry_newsave.get_text()
        nx = self.last_m_x
        ny = self.last_m_y
        node = Node(newtext, (nx, ny))
        main.add_object(node)

        # Push the node back into the draw area if its new position is outside.
        if nx < 0:
            nx = 0
        if ny < 0:
            ny = 0
        if nx + node.ext_width >= main.drawarea_size[0] + main.drawarea_extra[0]:
            nx = main.drawarea_size[0] - node.ext_width
        if ny + node.ext_height >= main.drawarea_size[1] + main.drawarea_extra[1]:
            ny = main.drawarea_size[1] - node.ext_height
        node.x = nx
        node.y = ny

        self.entry_newsave.set_text("")
        self.dialog_newsave.hide()
        self.selected_node_ids = [node.node_id]

        self.save_sbr()
        self.redraw()

    def cb_newsave_canceled(self, widget):
        self.entry_newsave.set_text("")
        self.dialog_newsave.hide()

    def cb_newsave_keyrelease(self, widget, event):
        if event.keyval == Gdk.KEY_Return:  # !: Should probably also only do this only if Ok is highlighted.
            self.cb_newsave_confirmed(widget)
        if event.keyval == Gdk.KEY_Escape:
            self.entry_newsave.set_text("")
            self.dialog_newsave.hide()

    def cb_keypress(self, widget, event, data=None):
        # WIP: Key auto-repeat is manageable if a flag is set on each pressed, reset on released.
        #if event.keyval == Gdk.KEY_Escape:
        #    self.destroy()  # WIP: Add quit dialog.
        if event.keyval == Gdk.KEY_Delete:
            self.cb_removenodes(None)
        if event.keyval == Gdk.KEY_Control_L:
            self.mod_ctrl = True
        if event.keyval == Gdk.KEY_Control_R:
            self.mod_ctrl = True
        if event.keyval == Gdk.KEY_Shift_L:
            self.mod_shift = True
        if event.keyval == Gdk.KEY_Shift_R:
            self.mod_shift = True
        if event.keyval == Gdk.KEY_h:
            if self.bars_hidden == True:
                self.menubar1.show()
                self.box1.show()
                self.bars_hidden = False
            elif self.bars_hidden == False:
                self.menubar1.hide()
                self.box1.hide()
                self.bars_hidden = True

        if event.keyval == Gdk.KEY_Right:
            if self.selected_node_ids:
                for node_id in self.selected_node_ids:
                    Objects.nodes[node_id].x += 1
                self.redraw()
        if event.keyval == Gdk.KEY_Down:
            if self.selected_node_ids:
                for node_id in self.selected_node_ids:
                    Objects.nodes[node_id].y += 1
                self.redraw()
        if event.keyval == Gdk.KEY_Left:
            if self.selected_node_ids:
                for node_id in self.selected_node_ids:
                    Objects.nodes[node_id].x -= 1
                self.redraw()
        if event.keyval == Gdk.KEY_Up:
            if self.selected_node_ids:
                for node_id in self.selected_node_ids:
                    Objects.nodes[node_id].y -= 1
                self.redraw()

    def cb_keyrelease(self, widget, event, data=None):
        if event.keyval == Gdk.KEY_Control_L:
            self.mod_ctrl = False
        if event.keyval == Gdk.KEY_Control_R:
            self.mod_ctrl = False
        if event.keyval == Gdk.KEY_Shift_L:
            self.mod_shift = False
        if event.keyval == Gdk.KEY_Shift_R:
            self.mod_shift = False

    def cb_windowresize(self, widget):
        pass

    def cb_draw(self, widget, cr):
        allocation = self.widget_area.get_allocation()
        w = allocation.width
        h = allocation.height
        main.drawarea_size = [w, h]

        cr.set_source_rgba(0, 0, 0, 1.0)
        cr.rectangle(0, 0, main.drawarea_size[0] + main.drawarea_extra[0], main.drawarea_size[1] + main.drawarea_extra[1])
        cr.fill()

        # Text size/alignment.
        #print (main.node_id_list)
        for node_id in main.node_id_list:
            node = Objects.nodes[node_id]
            cr.set_font_size(32)
            cr.select_font_face("m5x7")
            node.text_x, node.text_y, node.text_width, node.text_height, dx, dy = cr.text_extents(node.text)
            node.ext_width = node.text_width
            node.ext_height = node.text_height
            pad_width = 6 #node.w - padding
            pad_height = 4 #node.h - padding
            if node.text_width > pad_width:
                node.ext_width = node.w + (node.text_width - pad_width)
            else:
                node.ext_width = node.w
            if node.text_height > pad_height:
                node.ext_height = node.h + (node.text_height - pad_height)
            else:
                node.ext_height = node.h

        # Draw lines.
        for node_id in main.node_id_list:
            node = Objects.nodes[node_id]
            for sub_node_id in node.sub_node_ids:
                sub_node = Objects.nodes[sub_node_id]
                arrow_length = 14
                arrow_degrees = 10
                # Arrow/Line Positions.
                startx = node.x + (node.ext_width / 2)
                starty = node.y + (node.ext_height / 2)
                endx = sub_node.x + (sub_node.ext_width / 2)
                endy = sub_node.y + (sub_node.ext_height / 2)
                difx = (endx - startx) / 3
                dify = (endy - starty) / 3
                arrow_endx = endx - difx
                arrow_endy = endy - dify

                # Draw lines between nodes.
                cr.set_line_cap(0)
                cr.set_source_rgba(0.098039215, 0.4, 1, 1.0)
                cr.move_to(startx, starty)
                cr.set_line_width(4)
                cr.set_dash([])
                cr.line_to(endx, endy)
                cr.stroke()
                cr.fill()

                # Draw arrows between nodes.
                line_angle = math.atan2(arrow_endy - endy, arrow_endx - endx) + math.pi
                p1_x = arrow_endx + arrow_length * math.cos(line_angle - arrow_degrees)
                p1_y = arrow_endy + arrow_length * math.sin(line_angle - arrow_degrees)
                p2_x = arrow_endx + arrow_length * math.cos(line_angle + arrow_degrees)
                p2_y = arrow_endy + arrow_length * math.sin(line_angle + arrow_degrees)
                cr.set_line_cap(cairo.LINE_CAP_SQUARE)
                cr.set_dash([])
                cr.set_line_width(3)
                cr.set_source_rgba(0.098039215, 0.4, 1, 1.0)
                cr.move_to(p1_x, p1_y)
                cr.line_to(arrow_endx, arrow_endy)
                cr.line_to(p2_x, p2_y)
                cr.line_to(p1_x, p1_y)
                cr.close_path()
                cr.stroke_preserve()
                cr.fill()

        for node_id in main.node_id_list:
            node = Objects.nodes[node_id]
            # Draw boxes
            cr.set_line_width(4)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)

            # !: Using dashed lines fudges the rectangle outward. Maybe just slightly adjusting them works. (+1.., -2..)
            if self.target_node_id == node_id:
                cr.set_source_rgba(1, 1, 0, 1.0)
                cr.rectangle(node.x+1, node.y+1, node.ext_width-2, node.ext_height-2)
                cr.stroke()
                cr.fill()
            elif node_id in self.selected_node_ids:
                cr.set_source_rgba(1, 1, 1, 1.0)
                cr.rectangle(node.x+1, node.y+1, node.ext_width-2, node.ext_height-2)
                cr.stroke()
                cr.fill()
            else:
                cr.set_source_rgba(0.098039215, 0.4, 1, 1.0)
                cr.rectangle(node.x+1, node.y+1, node.ext_width-2, node.ext_height-2)
                cr.stroke()
                cr.fill()
            cr.set_source_rgba(0, 0, 0, 1.0)
            cr.rectangle(node.x + 2, node.y + 2, node.ext_width - 4, node.ext_height - 4)
            cr.fill()

            # Draw text.
            cr.set_source_rgba(1, 1, 1, 1.0)
            cr.move_to((node.x + node.ext_width / 2) - node.text_width / 2 - node.text_x,
                       (node.y + node.ext_height / 2) - node.text_height / 2 - node.text_y)
            cr.show_text(node.text)


def on_activate(app):
    # Show the application window
    win = AppWindow()
    win.props.application = app
    win.set_title("SaveBrancher")
    win.set_default_size(1280, 720)
    win.connect('key-press-event', win.cb_keypress)
    win.connect('key-release-event', win.cb_keyrelease)
    win.connect('focus-in-event', win.cb_focus_in)
    win.show()


def finish(self, widget, data=None):
    self.destroy()


if __name__ == '__main__':
    app = Gtk.Application(application_id='digidigi.savebrancher', flags=Gio.ApplicationFlags.FLAGS_NONE)
    # Activate reveals the application window.
    app.connect('activate', on_activate)
    app.run()

