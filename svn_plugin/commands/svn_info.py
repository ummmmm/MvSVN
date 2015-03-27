import sublime, sublime_plugin

import os
import xml.etree.ElementTree as ET

from ..settings 					import Settings
from ..repository 					import Repository
from ..thread_progress 				import ThreadProgress
from ..threads.revision_file 		import RevisionFileThread
from ..threads.annotate_file 		import AnnotateFileThread
from ..threads.revision_list_load 	import RevisionListLoadThread

class SvnPluginInfoCommand( sublime_plugin.WindowCommand ):
	def run( self, file = False, directory = False ):
		if ( file == directory ):
			return

		self.settings				= Settings()
		self.repository				= None
		self.file_path				= self.window.active_view().file_name()
		self.commit_panel			= None
		self.validate_file_paths	= set()
		self.__error				= ''

		if directory:
			return self.repository_quick_panel()

		return self.file_quick_panel( self.file_path )

	def repository_quick_panel( self ):
		self.repository = Repository()

		self.repository.valid_repositories()

		if len( self.repository.repositories ) == 0:
			return sublime.error_message( 'No repositories configured' )

		self.show_quick_panel( [ repository for repository in self.repository.repositories ], lambda index: self.repository_quick_panel_callback( list( self.repository.repositories ), index ) )

	def repository_quick_panel_callback( self, repositories, index ):
		if index == -1:
			return

		path 			= repositories[ index ]
		self.repository = Repository( path )

		entries = [ { 'code': 'up', 'value': '..' }, { 'code': 'vf', 'value': 'View Files' }, { 'code': 'vr', 'value': 'View Revisions' } ]

		if self.repository.is_modified():
			entries.insert( 2, { 'code': 'mf', 'value': 'View Modified Files' } )

		self.show_quick_panel( [ entry[ 'value' ] for entry in entries ], lambda index: self.repository_action_callback( entries, index ) )

	def repository_action_callback( self, repositories, index ):
		if index == -1:
			return
		elif index == 0:
			return self.repository_quick_panel()

		code = repositories[ index ][ 'code' ]

		if code == 'vr':
			return self.repository_revisions()

	def repository_revisions( self ):
		thread = RevisionListLoadThread( self.repository, log_limit = self.settings.svn_log_limit(), revision = None, on_complete = self.repository_revisions_callback )
		thread.start()
		ThreadProgress( thread, 'Loading revisions' )

	def repository_revisions_callback( self, result ):
		if not result:
			return sublime.error_message( self.repository.svn_error )


	def file_quick_panel( self, file_path ):
		if self.repository is None or self.repository.path != file_path:
			self.repository = Repository( file_path )

			if not self.repository.valid():
				return sublime.error_message( self.repository.error )

		if not self.repository.is_tracked():
			top_level_file_entries = [ { 'code': 'af', 'value': 'Add File to Repository' } ]
		else:
			top_level_file_entries = [ { 'code': 'vr', 'value': 'Revisions' } ]

			if self.repository.is_modified():
				top_level_file_entries.extend( [ { 'code': 'cf', 'value': 'Commit' }, { 'code': 'rf', 'value': 'Revert' }, { 'code': 'df', 'value': 'Diff' } ] )

		self.show_quick_panel( [ entry[ 'value' ] for entry in top_level_file_entries ], lambda index: self.file_quick_panel_callback( file_path, top_level_file_entries, index ) )

	def file_quick_panel_callback( self, file_path, entries, index ):
		if index == -1:
			return

		offset	= 0
		code 	= entries[ index - offset ][ 'code' ]

		if code == 'af':
			return self.file_add()
		elif code == 'rf':
			return self.file_revert()
		elif code == 'vr':
			return self.file_revisions()
		elif code == 'cf':
			return self.file_commit()
		elif code == 'df':
			return self.file_diff()

	def file_add( self ):
		return self.window.run_command( 'svn_plugin_add', { 'path': self.repository.path } )

	def file_revert( self ):
		if not sublime.ok_cancel_dialog( 'Are you sure you want to revert file:\n\n{0}' . format( self.repository.path ), 'Yes, revert' ):
			return sublime.status_message( 'File not reverted' )

		if not self.repository.revert():
			return sublime.error_message( self.repository.error )

		return sublime.status_message( 'File reverted' )

	def file_commit( self ):
		return self.window.run_command( 'svn_plugin_commit', { 'path': self.repository.path } )

	def file_diff( self, revision = None ):
		return self.window.run_command( 'svn_plugin_diff', { 'path': self.repository.path, 'revision': revision } )

	def file_revisions( self ):
		thread = RevisionListLoadThread( self.repository, log_limit = self.settings.svn_log_limit(), revision = None, on_complete = self.file_revisions_callback )
		thread.start()
		ThreadProgress( thread, 'Loading revisions' )

	def file_revisions_callback( self, result ):
		if not result:
			return sublime.error_message( self.repository.error )

		try:
			root = ET.fromstring( self.repository.svn_output )
		except ET.ParseError:
			return self.log_error( 'Failed to parse XML' )

		revisions = []

		for child in root.getiterator( 'logentry' ):
			revisions.append( { 'number': child.get( 'revision', '' ), 'author': child.findtext( 'author', '' ), 'date': child.findtext( 'date', '' ), 'message': child.findtext( 'msg', '' ) } )

		self.revisions_quick_panel( revisions )

	def file_annotate( self, revision ):
		return self.window.run_command( 'svn_plugin_file_annotate', { 'path': self.repository.path, 'revision': revision } )

	def file_revision( self, revision ):
		thread = RevisionFileThread( self.repository, revision = revision, on_complete = self.file_revision_callback )
		thread.start()
		ThreadProgress( thread, 'Loading revision', 'Revision loaded' )

	def file_revision_callback( self, result ):
		if not result:
			return sublime.error_message( self.repository.error )

		current_syntax	= self.window.active_view().settings().get( 'syntax' )
		view 			= self.window.new_file()

		view.set_name( 'SVNPlugin: Revision' )
		view.set_syntax_file( current_syntax )
		view.set_scratch( True )
		view.run_command( 'append', { 'characters': self.repository.svn_output } )
		view.set_read_only( True )


	def revisions_quick_panel( self, revisions, selected_index = -1 ):
		revisions_formatted = [ [ '..' ] ]

		for revision in revisions:
			revisions_formatted.extend( [ 'r{0} | {1} | {2}' . format( revision[ 'number' ], revision[ 'author' ], revision[ 'date' ] ) ] )

		self.show_quick_panel( revisions_formatted, lambda index: self.revisions_quick_panel_callback( revisions, index ), lambda index: self.revision_highlight( revisions, index ), selected_index = selected_index )

	def revisions_quick_panel_callback( self, revisions, index ):
		self.hide_panel()

		if index == -1:
			return
		elif index == 0:
			return self.file_quick_panel( self.repository.path )

		offset				= 1
		revision_index 		= index - offset
		entries 			= [ { 'code': 'up', 'value': '..' }, { 'code': 'vf', 'value': 'View' }, { 'code': 'af', 'value': 'Annotate' } ]

		if revision_index != 0 or self.repository.is_modified(): # only show diff option if the current revision has been modified locally or it's an older revision
			entries.insert( 2, { 'code': 'df', 'value': 'Diff' } )

		self.show_quick_panel( [ entry[ 'value' ] for entry in entries ], lambda index: self.revision_action_callback( entries, revisions, revision_index, index ) )

	def revision_action_callback( self, entries, revisions, revision_index, index ):
		if index == -1:
			return

		code = entries[ index ][ 'code' ]

		if code == 'up':
			return self.revisions_quick_panel( revisions, selected_index = revision_index + 1 )

		revision = revisions[ revision_index ]

		if code == 'vf':
			return self.file_revision( revision = revision[ 'number' ] )
		elif code == 'df':
			return self.file_diff( revision = revision[ 'number' ] )
		elif code == 'af':
			return self.file_annotate( revision = revision[ 'number' ] )

	def revision_highlight( self, revisions, index ):
		if index == -1:
			return
		elif index == 0:
			return self.show_panel( None )

		offset 		= 1
		revision	= revisions[ index - offset ]

		self.show_panel( revision[ 'message' ] )

	def show_quick_panel( self, entries, on_select, on_highlight = None, selected_index = -1 ):
		sublime.set_timeout( lambda: self.window.show_quick_panel( entries, on_select, on_highlight = on_highlight, selected_index = selected_index ), 10 )

	def show_panel( self, content ):
		if self.settings.svn_log_panel():
			self.commit_panel = self.window.create_output_panel( 'svn_panel' )
			self.window.run_command( 'show_panel', { 'panel': 'output.svn_panel' } )
			self.commit_panel.set_read_only( False )
			self.commit_panel.run_command( 'append', { 'characters': content } )
			self.commit_panel.set_read_only( True )

	def hide_panel( self ):
		if self.commit_panel:
				self.window.run_command( 'hide_panel', { 'panel': 'output.svn_panel' } )
				self.commit_panel = None

	def log_error( self, error ):
		self.__error = error

		if self.settings.log_errors():
			print( error )

		return False

	@property
	def error( self ):
		return self.__error
