#!/bin/env python3

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import Gio
import cairo, math, os, shutil
from time import sleep
import pickle

class Main(object):
    def __init__(self):
        self.obj_list = []  # Collection of objects/node objects for rendering order.
        self.next_obj_id = -1

        # Nodes to ref for a particular function segment index. (Function chains are populated once indexing is done.)
        self.node_index = dict()  # Line index : [nodes, ]

        # Nodes outside of each function segment after indexing step.
        self.outside_nodes = dict()  # Line index : [nodes,]

        self.drawarea_size = []
        self.drawarea_extra = [0, 0]  # Extra amount of drawarea that is scrollable.
        self.window_size = [1280, 720]

        self.source_filepath = None  # This will be None while an sbr file is not accessed and source is not known.

    def new_obj_id(self):  # New object IDs.
        self.next_obj_id += 1
        return self.next_obj_id

    def adjust_indices(self, index):  # Adjust indices of the objects after the one being removed.
        adjust_list = self.obj_list[index + 1:]
        for obj in adjust_list:
            obj.render_index -= 1

    def bring_top(self, t_obj):  # Bring an object to the front of the rendering order.
        self.adjust_indices(t_obj.render_index)
        self.obj_list.pop(t_obj.render_index)    # Remove target object from rendering list.
        t_obj.render_index = len(self.obj_list)  # New rendering index at the end of the list.
        self.obj_list.append(t_obj)              # Add to the end of the list.

    def remove_object(self, t_obj):  # Remove an object from the rendering list.
        self.adjust_indices(t_obj.render_index)
        self.obj_list.pop(t_obj.render_index)

    def add_object(self, t_obj):  # Add an object to the rendering list.
        t_obj.render_index = len(self.obj_list)
        self.obj_list.append(t_obj)
main = Main()


class Edge(object):
    def __init__(self, super_node, sub_node, edgetype=0):
        self.super_node = super_node
        self.sub_node = sub_node
        self.edgetype = edgetype  # 0==Code line, 1==Function line.


# Prototype node object.
class Node(object):
    def __init__(self, text="default", pos=(0, 0)):
        self.super_edges = []
        self.sub_edges = []
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
        self.render_cairo = True             # True if this is a cairo-drawn element, false if Gtk.
        self.render_index = None             # Index of this node element in main.obj_list for rendering order.
        self.obj_id = main.new_obj_id()
        self.parameters = []                 # Function parameters.

        self.module_name = ''
        self.node_name = text                # Also the variable/instance name.

        self.module_calling = True           # If false, this node is a variable assignment or input without ().

        self.index_flag = False  # Keeps track of whether the node was indexed, then whether the code was written.

        main.add_object(self)

    def add_subnode(self, sub_node, edgetype=0):  # Creates an edge from this node to a subnode; connecting the two.
        edge = Edge(self, sub_node, edgetype)
        self.sub_edges.append(edge)
        sub_node.super_edges.append(edge)


class AppWindow(Gtk.ApplicationWindow):
    def __init__(self):
        Gtk.Window.__init__(self)
        self.set_icon_from_file('savebrancher.png')
        self.gladefile = "savebrancher.glade"
        self.builder = Gtk.Builder()                # Used to build gui objects from our glade file.
        self.builder.add_from_file(self.gladefile)  #
        self.builder.connect_signals(self)          # Connect the signals to our callbacks in this object.
        self.mainbox = self.builder.get_object("mainbox")
        self.mainbox.reparent(self)  # Glade has a separate parent window widget for previewing.

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

        self.flag_dragging = False
        self.grabbed_diff = [0, 0]  # Space between the position of a grabbed box and the cursor.
        self.grabbed_object = None
        self.selected_node = None
        self.selected_nodes = []
        self.target_node = None  # Object targeted with right click.
        self.mod_ctrl = False
        self.mod_shift = False

        # Last mouse positions (usually after right clicking a space)
        self.last_m_x = 0
        self.last_m_y = 0

        self.widget_area.set_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.eventbox.set_events(Gdk.EventMask.BUTTON_PRESS_MASK)

        # Node menu when no node is selected.
        self.spacemenu = Gtk.Menu()
        self.sm_appendsave = Gtk.MenuItem("Append new save")
        self.spacemenu.append(self.sm_appendsave)
        self.sm_appendsave.connect('button-press-event', self.cb_appendsave)
        self.sm_appendsave.show()
        self.sm_newsave = Gtk.MenuItem("Copy new save")
        self.spacemenu.append(self.sm_newsave)
        self.sm_newsave.connect('button-press-event', self.cb_newsave)
        self.sm_newsave.show()

        # Node menu right-clicking a node.
        self.nodemenu = Gtk.Menu()
        self.nm_rename = Gtk.MenuItem("Change Label")
        self.nodemenu.append(self.nm_rename)
        self.nm_rename.connect('button-press-event', self.cb_rename)
        self.nm_rename.show()
        self.nm_linksave = Gtk.MenuItem("Link")
        self.nodemenu.append(self.nm_linksave)
        self.nm_linksave.connect('button-press-event', self.cb_linksave)
        self.nm_linksave.show()
        self.nm_unlink = Gtk.MenuItem("Unlink")
        self.nodemenu.append(self.nm_unlink)
        self.nm_unlink.connect('button-press-event', self.cb_unlink)
        self.nm_unlink.show()
        self.nm_writesave = Gtk.MenuItem("Load save (Overwrite Slot)")
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

        self.file_newsource = Gtk.FileChooserDialog("Select a source state/save.", None, Gtk.FileChooserAction.OPEN,
                                                    (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                                                     Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        self.file_newsource.connect("response", self.cb_newsource_response)
        self.file_newsource.connect("delete-event", self.cb_delete_event)

        self.file_opentree = Gtk.FileChooserDialog("Select an existing tree file.", None, Gtk.FileChooserAction.OPEN,
                                                   (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                                                    Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        self.file_opentree.connect("response", self.cb_opentree_response)
        self.file_opentree.connect("delete-event", self.cb_delete_event)

        self.dialog_onload = self.builder.get_object("dialog_onload")
        self.dialog_onload.connect("delete-event", self.cb_delete_event)
        self.button_onload_cancel = self.builder.get_object("button_onload_cancel")
        self.button_onload_confirm = self.builder.get_object("button_onload_confirm")
        self.textview_onload = self.builder.get_object("textview_onload")
        self.textview_onload.set_buffer(self.onloadbuffer)

        self.dialog_warncreate = Gtk.MessageDialog(None, 0, Gtk.MessageType.INFO, (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                                                                                   Gtk.STOCK_OK, Gtk.ResponseType.OK), "Create savetree from:")
        self.dialog_warncreate.connect("response", self.cb_warncreate_response)
        self.dialog_warncreate.connect("delete-event", self.cb_delete_event)

        self.dialog_error = Gtk.MessageDialog(None, 0, Gtk.MessageType.ERROR, (Gtk.STOCK_OK, Gtk.ResponseType.OK), "Error.")
        self.dialog_error.connect("response", self.cb_error_response)
        self.dialog_error.connect("delete-event", self.cb_delete_event)

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

    def cb_warncreate_response(self, widget, response):
        global main
        if response == Gtk.ResponseType.OK:

            main = Main()
            main.source_filepath = self.temp_source_filepath[:]
            main.source_filename = os.path.split(main.source_filepath)[-1]  # Get filename.
            #main.tree_filename = main.source_filename.split('.')[0] + '.sbr'
            main.tree_filename = main.source_filename + '.sbr'
            treepath = os.path.split(main.source_filepath)[:-1][0]
            #main.tree_dirpath = os.path.join(treepath, main.source_filename.split('.')[0])
            main.tree_dirpath = os.path.join(treepath, main.source_filename) + ' SBR'
            main.tree_filepath = os.path.join(main.tree_dirpath, main.tree_filename)

            print (treepath, main.source_filename)
            print (main.tree_filepath)
            print (main.tree_dirpath)

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
                    main = pickle.load(sbrfile, encoding='latin1')

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
        self.menuitem_save.set_sensitive(False)

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
        fileprefix = main.source_filename + '.' + str(self.selected_node.obj_id)
        nodefilepath = os.path.join(main.tree_dirpath, fileprefix)
        shutil.copy2(nodefilepath, main.source_filepath)
        print (nodefilepath, main.source_filepath)
        #execfile('onloadscript.py') #py2
        with open("onloadscript.py") as f:
            code = compile(f.read(), "onloadscript.py", 'exec')
            exec(code)

    def cb_linksave(self, widget, data):
        for node in self.selected_nodes:
            if node is not self.target_node:
                # Conditional for preventing two-way edges.
                sub_edge_exists = 0
                for sub_edge in self.target_node.sub_edges:
                    if node is sub_edge.sub_node:
                        sub_edge_exists += 1
                        break  # Break for loop; sub_edge found.
                if sub_edge_exists < 1:
                    # Conditonal for preventing dupe same edges.
                    super_edge_exists = 0
                    for super_edge in self.target_node.super_edges:
                        if node is super_edge.super_node:
                            super_edge_exists += 1
                            break  # Break for loop; super_edge found.
                    if super_edge_exists < 1:
                        node.add_subnode(self.target_node, 1)
        self.target_node = None
        self.save_sbr()
        self.redraw()

    # Remove all edges/connections to and from this node.
    def cb_unlink(self, widget, data):
        for sub_edge in self.target_node.sub_edges:
            sub_edge.sub_node.super_edges.pop(sub_edge.sub_node.super_edges.index(sub_edge))
        self.target_node.sub_edges = []
        for super_edge in self.target_node.super_edges:
            super_edge.super_node.sub_edges.pop(super_edge.super_node.sub_edges.index(super_edge))
        self.target_node.super_edges = []
        self.save_sbr()
        self.redraw()

    def cb_rename(self, widget, data):
        if self.target_node:
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
        self.target_node = None
        foundnode = [False]
        for node in main.obj_list:
            if event.x >= node.x and event.x < node.x+node.ext_width:
                if event.y >= node.y and event.y < node.y+node.ext_height:
                    foundnode[0] = True

                    if event.button == Gdk.BUTTON_PRIMARY:
                        if self.mod_ctrl:
                            if node in self.selected_nodes:
                                sindex = self.selected_nodes.index(node)
                                self.selected_nodes.pop(sindex)
                            self.selected_nodes.append(node)
                            self.selected_node = node
                        else:
                            self.selected_nodes = [node]
                            self.selected_node = node
                        

                        self.flag_dragging = True
                        self.grabbed_object = node
                        self.grabbed_diff = [event.x - node.x, event.y - node.y]
                    elif event.button == Gdk.BUTTON_SECONDARY:
                        self.selected_node = node

                        self.target_node = node
                        self.nodemenu.popup(None, None, None, None, event.button, event.time)
                    idstring = ''
                    for node in self.selected_nodes:
                        idstring = idstring + str(node.obj_id) + ', '
                    idstring = idstring[:-2]
                    self.statusbar4.push(self.context_id4, idstring)

        if foundnode[0] is False:
            self.grabbed_object = None
            self.target_node = None

            if event.button == Gdk.BUTTON_PRIMARY:
                self.selected_nodes = []

            elif event.button == Gdk.BUTTON_SECONDARY:
                if main.source_filepath:
                    # Right-clicked on blank space: open space menu.
                    if len(self.selected_nodes) > 0:
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
            if len(self.selected_nodes) > 0:
                main.bring_top(self.selected_nodes[-1])
                self.redraw()
        self.eventbox.grab_focus()

    def cb_release(self, widget, event):
        self.flag_dragging = False
        self.grabbed_object = None
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
            if gox + self.grabbed_object.ext_width >= main.drawarea_size[0] + main.drawarea_extra[0]:
                main.drawarea_extra[0] += 4
                self.drawarea.set_size_request(main.drawarea_size[0] + main.drawarea_extra[0],
                                               main.drawarea_size[1] + main.drawarea_extra[1])
            if goy + self.grabbed_object.ext_height >= main.drawarea_size[1] + main.drawarea_extra[1]:
                main.drawarea_extra[1] += 4
                self.drawarea.set_size_request(main.drawarea_size[0] + main.drawarea_extra[0],
                                               main.drawarea_size[1] + main.drawarea_extra[1])
            self.grabbed_object.x = new_posx
            self.grabbed_object.y = new_posy

            self.unsaved_changes()

            self.redraw()

    def cb_removenodes(self, widget):
        # WIP: Should have a warning dialog before deletion.
        if len(self.selected_nodes) > 0:
            for node in self.selected_nodes:
                # Remove subedge reference for each node connected to this node.
                for superedge in node.super_edges:
                    for subedge in superedge.super_node.sub_edges:
                        if subedge is superedge:
                            superedge.super_node.sub_edges.index(subedge)
                            superedge.super_node.sub_edges.pop(superedge.super_node.sub_edges.index(subedge))  # aaaaa
                            break
                # Remove superedge reference for each node connected to this node.
                for subedge in node.sub_edges:
                    for superedge in subedge.sub_node.super_edges:
                        if superedge is subedge:
                            subedge.sub_node.super_edges.index(superedge)
                            subedge.sub_node.super_edges.pop(subedge.sub_node.super_edges.index(superedge))
                            break

                # Remove edges.
                node.super_edges = None
                node.sub_edges = None

                #nodefn = main.tree_filename.split('.')[0] + '.' + str(node.obj_id)
                nodefn = main.tree_filename[:-4] + '.' + str(node.obj_id)
                nodefp = os.path.join(main.tree_dirpath, nodefn)
                os.remove(nodefp)

                main.remove_object(node)

            self.selected_nodes = []
            self.grabbed_object = None
            self.target_node = None
            self.save_sbr()
            self.redraw()

    def cb_rename_confirmed(self, widget):
        self.target_node.text = self.entry_rename.get_text()
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
        if len(self.selected_nodes) > 0:
            self.dialog_appendsave.show()
        else:
            if len(main.obj_list) == 0:
                self.dialog_appendsave.show()
            else:
                self.dialog_appendsave.show()

    def cb_appendsave_confirmed(self, widget):

        # Copy source savefile to a node savefile.
        # WIP: Add error checking.
        #fileprefix = main.source_filename.split('.')[0] + '.' + str(main.next_obj_id + 1)
        fileprefix = main.source_filename + '.' + str(main.next_obj_id + 1)
        savedest = os.path.join(main.tree_dirpath, fileprefix)
        shutil.copy2(main.source_filepath, savedest)

        newtext = self.entry_appendsave.get_text()
        nx = self.last_m_x
        ny = self.last_m_y
        n = Node(newtext, (nx, ny))

        # Push the node back into the draw area if its new position is outside.
        if nx < 0:
            nx = 0
        if ny < 0:
            ny = 0
        if nx + n.ext_width >= main.drawarea_size[0] + main.drawarea_extra[0]:
            nx = main.drawarea_size[0] - n.ext_width
        if ny + n.ext_height >= main.drawarea_size[1] + main.drawarea_extra[1]:
            ny = main.drawarea_size[1] - n.ext_height
        n.x = nx
        n.y = ny

        self.entry_appendsave.set_text("")
        self.dialog_appendsave.hide()
        for sn in self.selected_nodes:
            sn.add_subnode(n, 1)

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
        if len(self.selected_nodes) > 0:
            self.dialog_newsave.show()
        else:
            if len(main.obj_list) == 0:
                self.dialog_newsave.show()
            else:
                self.dialog_newsave.show()

    def cb_newsave_confirmed(self, widget):

        # Copy source savefile to a node savefile.
        # WIP: Add error checking.
        #fileprefix = main.source_filename.split('.')[0] + '.' + str(main.next_obj_id + 1)
        fileprefix = main.source_filename + '.' + str(main.next_obj_id + 1)
        savedest = os.path.join(main.tree_dirpath, fileprefix)
        shutil.copy2(main.source_filepath, savedest)

        newtext = self.entry_newsave.get_text()
        nx = self.last_m_x
        ny = self.last_m_y
        n = Node(newtext, (nx, ny))

        # Push the node back into the draw area if its new position is outside.
        if nx < 0:
            nx = 0
        if ny < 0:
            ny = 0
        if nx + n.ext_width >= main.drawarea_size[0] + main.drawarea_extra[0]:
            nx = main.drawarea_size[0] - n.ext_width
        if ny + n.ext_height >= main.drawarea_size[1] + main.drawarea_extra[1]:
            ny = main.drawarea_size[1] - n.ext_height
        n.x = nx
        n.y = ny

        self.entry_newsave.set_text("")
        self.dialog_newsave.hide()
        self.selected_nodes = [n]

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

        #cr.set_source_rgba(0.1, 0.15, 0.3, 1.0)
        cr.set_source_rgba(0, 0, 0, 1.0)
        cr.rectangle(0, 0, main.drawarea_size[0] + main.drawarea_extra[0], main.drawarea_size[1] + main.drawarea_extra[1])
        cr.fill()

        # Text size/alignment.
        for node in main.obj_list:
            cr.set_font_size(32)
            #cr.select_font_face("Bitstream Vera Sans")
            cr.select_font_face("m5x7")
            node.text_x, node.text_y, node.text_width, node.text_height, dx, dy = cr.text_extents(node.text)
            node.ext_width = node.text_width
            node.ext_height = node.text_height
            padding = 32
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
        for node in main.obj_list:
            supernodeindex = 0

            for superedge in node.super_edges:
                supernode = superedge.super_node

                arrow_length = 14
                arrow_degrees = 10
                # Arrow/Line Positions.
                endx = node.x + (node.ext_width / 2)
                endy = node.y + (node.ext_height / 2)
                startx = supernode.x + (supernode.ext_width / 2)
                starty = supernode.y + (supernode.ext_height / 2)
                difx = (endx - startx) / 3
                dify = (endy - starty) / 3
                arrow_endx = endx - difx
                arrow_endy = endy - dify

                # Draw lines between nodes.
                cr.set_line_cap(0)
                #cr.set_source_rgba(0.5, 0.5, .8, 1.0)
                cr.set_source_rgba(0.098039215, 0.4, 1, 1.0)
                cr.move_to(startx, starty)
                cr.set_line_width(4)

                if superedge.edgetype == 0:
                    cr.set_dash([2, 4, 2])
                elif superedge.edgetype == 1:
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
                #cr.set_source_rgba(1, 1, 1, 1.0)
                #cr.set_source_rgba(0.5, 0.5, .8, 1.0)
                cr.set_source_rgba(0.098039215, 0.4, 1, 1.0)
                cr.move_to(p1_x, p1_y)
                cr.line_to(arrow_endx, arrow_endy)
                cr.line_to(p2_x, p2_y)
                cr.line_to(p1_x, p1_y)
                cr.close_path()

                cr.stroke_preserve()
                cr.fill()
                supernodeindex += 1

        for node in main.obj_list:
            # Draw boxes
            cr.set_line_width(4)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)

            if node.module_calling is True:
                cr.set_dash([])
            else:
                cr.set_dash([5])

            # !: Using dashed lines fudges the rectangle outward. Maybe just slightly adjusting them works. (+1.., -2..)
            if self.target_node == node:
                cr.set_source_rgba(1, 1, 0, 1.0)
                cr.rectangle(node.x+1, node.y+1, node.ext_width-2, node.ext_height-2)
                cr.stroke()
                cr.fill()
            elif node in self.selected_nodes:
                cr.set_source_rgba(1, 1, 1, 1.0)
                cr.rectangle(node.x+1, node.y+1, node.ext_width-2, node.ext_height-2)
                cr.stroke()
                cr.fill()
            else:
                #cr.set_source_rgba(0.5, 0.5, .8, 1.0)
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
    app = Gtk.Application(application_id='com.dgdg.savebrancher', flags=Gio.ApplicationFlags.FLAGS_NONE)
    # Activate reveals the application window.
    app.connect('activate', on_activate)
    #print Gtk.Application.__gsignals__
    app.run()

