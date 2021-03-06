# EMACS settings: -*-  tab-width: 2; indent-tabs-mode: t; python-indent-offset: 2 -*-
# vim: tabstop=2:shiftwidth=2:noexpandtab
# kate: tab-width 2; replace-tabs off; indent-width 2;
# 
# ==============================================================================
# Authors:               Patrick Lehmann
#												Martin Zabel
# 
# Python Main Module:    Entry point to the testbench tools in PoC repository.
# 
# Description:
# ------------------------------------
#    This is a python main module (executable) which:
#    - runs automated testbenches,
#    - ...
#
# License:
# ==============================================================================
# Copyright 2007-2016 Technische Universitaet Dresden - Germany
#                     Chair for VLSI-Design, Diagnostics and Architecture
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#    http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# distributed under the License is distributed on an "AS IS" BASIS,default
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

from argparse                       import RawDescriptionHelpFormatter
from collections                    import OrderedDict
from configparser                   import Error as ConfigParser_Error, DuplicateOptionError
from os                             import environ
from pathlib                        import Path
from platform                       import system as platform_system
from sys                            import argv as sys_argv
from textwrap                       import dedent

from Base.Compiler                  import CompilerException
from Base.Configuration             import ConfigurationException, SkipConfigurationException
from Base.Exceptions                import ExceptionBase, CommonException, PlatformNotSupportedException, EnvironmentException, NotConfiguredException
from Base.Logging                   import ILogable, Logger, Severity
from Base.Project                   import VHDLVersion
from Base.Simulator                 import SimulatorException
from Base.ToolChain                 import ToolChainException
from Compiler.LSECompiler           import Compiler as LSECompiler
from Compiler.QuartusCompiler       import Compiler as MapCompiler
from Compiler.XCOCompiler           import Compiler as XCOCompiler
from Compiler.XSTCompiler           import Compiler as XSTCompiler
from Compiler.VivadoCompiler        import Compiler as VivadoCompiler
from PoC.Config                     import Board
from PoC.Entity                     import NamespaceRoot, FQN, EntityTypes, WildCard, TestbenchKind, NetlistKind
from PoC.Solution                   import Repository
from PoC.Query                      import Query
from Simulator.ActiveHDLSimulator   import Simulator as ActiveHDLSimulator
from Simulator.CocotbSimulator      import Simulator as CocotbSimulator
from Simulator.GHDLSimulator        import Simulator as GHDLSimulator
from Simulator.ISESimulator         import Simulator as ISESimulator
from Simulator.QuestaSimulator      import Simulator as QuestaSimulator
from Simulator.VivadoSimulator      import Simulator as VivadoSimulator
from ToolChains                     import Configurations
from ToolChains.GHDL                import Configuration as GHDLConfiguration
from lib.ArgParseAttributes         import ArgParseMixin
from lib.ArgParseAttributes         import CommandAttribute, CommandGroupAttribute, ArgumentAttribute, SwitchArgumentAttribute, DefaultAttribute
from lib.ArgParseAttributes         import CommonArgumentAttribute, CommonSwitchArgumentAttribute
from lib.ConfigParser               import ExtendedConfigParser
from lib.Functions                  import Init, Exit
from lib.Parser                     import ParserException
from lib.pyAttribute                import Attribute


class PoCEntityAttribute(Attribute):
	def __call__(self, func):
		self._AppendAttribute(func, ArgumentAttribute(metavar="<PoC Entity>", dest="FQN", type=str, nargs='+', help="A space seperated list of PoC entities."))
		return func

class BoardDeviceAttributeGroup(Attribute):
	def __call__(self, func):
		self._AppendAttribute(func, ArgumentAttribute("--device", metavar="<DeviceName>", dest="DeviceName", help="The target platform's device name."))
		self._AppendAttribute(func, ArgumentAttribute("--board", metavar="<BoardName>", dest="BoardName", help="The target platform's board name."))
		return func

class VHDLVersionAttribute(Attribute):
	def __call__(self, func):
		self._AppendAttribute(func, ArgumentAttribute("--std", metavar="<VHDLVersion>", dest="VHDLVersion", help="Simulate with VHDL-??"))
		return func

class GUIModeAttribute(Attribute):
	def __call__(self, func):
		self._AppendAttribute(func, SwitchArgumentAttribute("-g", "--gui", dest="GUIMode", help="show waveform in a GUI window."))
		return func

class NoCleanUpAttribute(Attribute):
	def __call__(self, func):
		self._AppendAttribute(func, SwitchArgumentAttribute("--no-cleanup", dest="NoCleanUp", help="Don't delete intermediate files. Skip post-delete rules."))
		return func

class PoC(ILogable, ArgParseMixin):
	HeadLine =                "The PoC-Library - Service Tool"

	# configure hard coded variables here
	__CONFIGFILE_DIRECTORY =  "py"
	__CONFIGFILE_PRIVATE =    "config.private.ini"
	__CONFIGFILE_DEFAULTS =   "config.defaults.ini"
	__CONFIGFILE_BOARDS =     "config.boards.ini"
	__CONFIGFILE_STRUCTURE =  "config.structure.ini"
	__CONFIGFILE_IPCORES =    "config.entity.ini"

	# load platform information (Windows, Linux, Darwin, ...)
	__PLATFORM =              platform_system()

	# records
	class __Directories__:
		Working =     None
		Root =        None
		ConfigFiles = None
		Solution =    None
		Project =     None
		Source =      None
		Testbench =   None
		Netlist =     None
		Temp =        None
		PreCompiled = None

	class __ConfigFiles__:
		Private =     None
		Defaults =    None
		Boards =      None
		Structure =   None
		IPCores =     None
		Solution =    None
		Project =     None


	def __init__(self, debug, verbose, quiet, dryRun):
		# Call the initializer of ILogable
		# --------------------------------------------------------------------------
		if quiet:      severity = Severity.Quiet
		elif debug:    severity = Severity.Debug
		elif verbose:  severity = Severity.Verbose
		else:          severity = Severity.Normal

		logger = Logger(self, severity, printToStdOut=True)
		ILogable.__init__(self, logger=logger)

		# Do some basic checks
		self.__CheckEnvironment()

		# Call the constructor of the ArgParseMixin
		# --------------------------------------------------------------------------
		description = dedent("""\
			This is the PoC-Library Service Tool.
			""")
		epilog = "Epidingsbums"

		class HelpFormatter(RawDescriptionHelpFormatter):
			def __init__(self, *args, **kwargs):
				kwargs['max_help_position'] = 25
				super().__init__(*args, **kwargs)

		ArgParseMixin.__init__(self, description=description, epilog=epilog, formatter_class=HelpFormatter, add_help=False)

		# declare members
		# --------------------------------------------------------------------------
		self.__dryRun =       dryRun
		self.__pocConfig =    None
		self.__root =         None
		self.__repo =         None
		self.__directories =  {}

		self.__SimulationDefaultVHDLVersion = VHDLVersion.VHDL2008
		self.__SimulationDefaultBoard =       None

		self._directories =             self.__Directories__()
		self._directories.Working =     Path.cwd()
		self._directories.Root =        Path(environ.get('PoCRootDirectory'))
		self._directories.ConfigFiles = self.Directories.Root / self.__CONFIGFILE_DIRECTORY

		self._configFiles =             self.__ConfigFiles__()
		self._configFiles.Private =     self.Directories.ConfigFiles / self.__CONFIGFILE_PRIVATE
		self._configFiles.Defaults =    self.Directories.ConfigFiles / self.__CONFIGFILE_DEFAULTS
		self._configFiles.Boards =      self.Directories.ConfigFiles / self.__CONFIGFILE_BOARDS
		self._configFiles.Structure =   self.Directories.ConfigFiles / self.__CONFIGFILE_STRUCTURE
		self._configFiles.IPCores =     self.Directories.ConfigFiles / self.__CONFIGFILE_IPCORES

	# class properties
	# ============================================================================
	@property
	def Platform(self):           return self.__PLATFORM
	@property
	def DryRun(self):             return self.__dryRun

	@property
	def Directories(self):        return self._directories
	@property
	def ConfigFiles(self):        return self._configFiles

	@property
	def PoCConfig(self):          return self.__pocConfig
	@property
	def Root(self):               return self.__root
	@property
	def Repository(self):         return self.__repo

	def __CheckEnvironment(self):
		if (self.Platform not in ["Windows", "Linux", "Darwin"]):  raise PlatformNotSupportedException(self.Platform)
		if (environ.get('PoCRootDirectory') is None):              raise EnvironmentException("Shell environment does not provide 'PoCRootDirectory' variable.")

	# read PoC configuration
	# ============================================================================
	def __ReadPoCConfiguration(self):
		self._LogVerbose("Reading configuration files...")

		configFiles = [
			(self.ConfigFiles.Private,		"private"),
			(self.ConfigFiles.Defaults,		"defaults"),
			(self.ConfigFiles.Boards,			"boards"),
			(self.ConfigFiles.Structure,	"structure"),
			(self.ConfigFiles.IPCores,		"IP core")
		]

		# create parser instance
		self._LogDebug("Reading PoC configuration from:")
		self.__pocConfig = ExtendedConfigParser()
		self.__pocConfig.optionxform = str

		try:
			# process first file (private)
			file, name = configFiles[0]
			self._LogDebug("  {0!s}".format(file))
			if not file.exists():  raise NotConfiguredException("PoC's {0} configuration file '{1!s}' does not exist.".format(name, file))  from FileNotFoundError(str(file))
			self.__pocConfig.read(str(file))

			for file, name in configFiles[1:]:
				self._LogDebug("  {0!s}".format(file))
				if not file.exists():  raise ConfigurationException("PoC's {0} configuration file '{1!s}' does not exist.".format(name, file))  from FileNotFoundError(str(file))
				self.__pocConfig.read(str(file))
		except DuplicateOptionError as ex:
			raise ConfigurationException("Error in configuration file '{0!s}'.".format(file)) from ex

		# check PoC installation directory
		if (self.Directories.Root != Path(self.PoCConfig['INSTALL.PoC']['InstallationDirectory'])):
			raise NotConfiguredException("There is a mismatch between PoCRoot and PoC installation directory.")

		# parsing values into class fields
		configSection =                 self.PoCConfig['CONFIG.DirectoryNames']
		self.Directories.Source =       self.Directories.Root / configSection['HDLSourceFiles']
		self.Directories.Testbench =    self.Directories.Root / configSection['TestbenchFiles']
		self.Directories.NetList =      self.Directories.Root / configSection['NetlistFiles']
		self.Directories.Temp =         self.Directories.Root / configSection['TemporaryFiles']
		self.Directories.PreCompiled =  self.Directories.Root / configSection['PrecompiledFiles']

		# Initialize the default board (GENERIC)
		self.__SimulationDefaultBoard = Board(self)

		# Initialize PoC's namespace structure
		self.__root = NamespaceRoot(self)
		self.__repo = Repository(self)

	def __WritePoCConfiguration(self):
		for sectionName in [sectionName for sectionName in self.__pocConfig if not (sectionName.startswith("INSTALL") or sectionName.startswith("SOLUTION"))]:
			self.__pocConfig.remove_section(sectionName)

		self.__pocConfig.remove_section("SOLUTION.DEFAULTS")

		# Writing configuration to disc
		self._LogNormal("Writing configuration file to '{0!s}'".format(self._configFiles.Private))
		with self._configFiles.Private.open('w') as configFileHandle:
			self.PoCConfig.write(configFileHandle)

	def __PrepareForConfiguration(self):
		self.__ReadPoCConfiguration()

	def __PrepareForSimulation(self):
		self._LogNormal("Initializing PoC-Library Service Tool for simulations")
		self.__ReadPoCConfiguration()

	def __PrepareForSynthesis(self):
		self._LogNormal("Initializing PoC-Library Service Tool for synthesis")
		self.__ReadPoCConfiguration()

	# ============================================================================
	# Common commands
	# ============================================================================
	# common arguments valid for all commands
	# ----------------------------------------------------------------------------
	@CommonSwitchArgumentAttribute("-D",              dest="DEBUG",   help="enable script wrapper debug mode")
	@CommonSwitchArgumentAttribute(      "--dryrun",  dest="DryRun",  help="enable script wrapper debug mode")
	@CommonSwitchArgumentAttribute("-d", "--debug",   dest="debug",   help="enable debug mode")
	@CommonSwitchArgumentAttribute("-v", "--verbose", dest="verbose", help="print out detailed messages")
	@CommonSwitchArgumentAttribute("-q", "--quiet",   dest="quiet",   help="reduce messages to a minimum")
	@CommonArgumentAttribute("--sln", metavar="<SolutionID>", dest="SolutionID", help="Solution name")
	@CommonArgumentAttribute("--prj", metavar="<ProjectID>", dest="ProjectID", help="Solution name")
	def Run(self):
		ArgParseMixin.Run(self)

	def PrintHeadline(self):
		self._LogNormal("{HEADLINE}{line}{NOCOLOR}".format(line="="*80, **Init.Foreground))
		self._LogNormal("{HEADLINE}{headline: ^80s}{NOCOLOR}".format(headline=self.HeadLine, **Init.Foreground))
		self._LogNormal("{HEADLINE}{line}{NOCOLOR}".format(line="="*80, **Init.Foreground))

	# ----------------------------------------------------------------------------
	# fallback handler if no command was recognized
	# ----------------------------------------------------------------------------
	@DefaultAttribute()
	def HandleDefault(self, _):
		self.PrintHeadline()

		# print("Common arguments:")
		# for funcname,func in CommonArgumentAttribute.GetMethods(self):
		# 	for comAttribute in CommonArgumentAttribute.GetAttributes(func):
		# 		print("  {0}  {1}".format(comAttribute.Args, comAttribute.KWArgs['help']))
		#
		# 		self.__mainParser.add_argument(*(comAttribute.Args), **(comAttribute.KWArgs))
		#
		# for funcname,func in CommonSwitchArgumentAttribute.GetMethods(self):
		# 	for comAttribute in CommonSwitchArgumentAttribute.GetAttributes(func):
		# 		print("  {0}  {1}".format(comAttribute.Args, comAttribute.KWArgs['help']))

		self.MainParser.print_help()
		Exit.exit()

	# ----------------------------------------------------------------------------
	# create the sub-parser for the "help" command
	# ----------------------------------------------------------------------------
	@CommandAttribute("help", help="help help")
	@ArgumentAttribute(metavar="<Command>", dest="Command", type=str, nargs="?", help="Print help page(s) for a command.")
	def HandleHelp(self, args):
		self.PrintHeadline()
		if (args.Command is None):
			self.MainParser.print_help()
			Exit.exit()
		elif (args.Command == "help"):
			print("This is a recursion ...")
		else:
			self.SubParsers[args.Command].print_help()
		Exit.exit()

	# ============================================================================
	# Configuration commands
	# ============================================================================
	# create the sub-parser for the "configure" command
	# ----------------------------------------------------------------------------
	@CommandGroupAttribute("Configuration commands")
	@CommandAttribute("configure", help="Configure vendor tools for PoC.")
	def HandleConfiguration(self, _):
		self.PrintHeadline()

		if (self.Platform not in ["Darwin", "Linux", "Windows"]):    raise PlatformNotSupportedException(self.Platform)

		try:
			self.__ReadPoCConfiguration()
			self.__UpdateConfiguration()
		except NotConfiguredException:
			self._InitializeConfiguration()

		self._LogVerbose("starting manual configuration...")
		print("Explanation of abbreviations:")
		print("  y - yes")
		print("  n - no")
		print("  p - pass (jump to next question)")
		print("Upper case means default value")
		print()

		# configure each vendor or tool of a tool chain
		configurators = [config(self) for config in Configurations]
		for configurator in configurators:

			# skip configuration with unsupported platforms
			if (not configurator.IsSupportedPlatform()):  continue
			# skip configuration if dependency is not fulfilled
			if (not configurator.CheckDependency()):
				configurator.ClearSection()
				continue

			self._LogNormal("{CYAN}Configuring {0!s}{NOCOLOR}".format(configurator, **Init.Foreground))
			nxt = False
			while (nxt is False):
				try:
					if   (self.Platform == "Darwin"):    configurator.ConfigureForDarwin()
					elif (self.Platform == "Linux"):    configurator.ConfigureForLinux()
					elif (self.Platform == "Windows"):  configurator.ConfigureForWindows()

					nxt = True
				except SkipConfigurationException:
					break
				except ExceptionBase as ex:
					print("  {RED}FAULT:{NOCOLOR} {0}".format(ex.message, **Init.Foreground))

		# write and re-read configuration
		self.__WritePoCConfiguration()
		self.__ReadPoCConfiguration()

		# run post-configuration tasks
		self._LogNormal("{CYAN}Running post configuration tasks{NOCOLOR}".format(**Init.Foreground))
		for configurator in configurators:
			configurator.RunPostConfigurationTasks()

	def _InitializeConfiguration(self):
		self._LogWarning("No private configuration found. Generating an empty PoC configuration...")

		for config in Configurations:
			for sectionName in config.GetSections(self.Platform):
				self.__pocConfig[sectionName] = OrderedDict()

	def __UpdateConfiguration(self):
		pocSections =      set([sectionName for sectionName in self.__pocConfig])
		configSections =  set([sectionName for config in Configurations for sectionName in config.GetSections(self.Platform)])

		addSections = configSections.difference(pocSections)
		delSections = pocSections.difference(configSections)

		if addSections:
			self._LogWarning("Adding new sections to configuration...")
			for sectionName in addSections:
				self._LogWarning("  Adding [{0}]".format(sectionName))
				self.__pocConfig[sectionName] = OrderedDict()

		if delSections:
			for sectionName in delSections:
				self.__pocConfig.remove_section(sectionName)

	# ----------------------------------------------------------------------------
	# create the sub-parser for the "add-solution" command
	# ----------------------------------------------------------------------------
	@CommandGroupAttribute("Configuration commands")
	@CommandAttribute("add-solution", help="Add a solution to PoC.")
	def HandleAddSolution(self, _): #args
		self.PrintHeadline()
		self.__PrepareForConfiguration()

		self._LogNormal("Register a new solutions in PoC")
		solutionName = input("  Solution name: ")
		if (solutionName == ""):        raise ConfigurationException("Empty input. Aborting!")

		solutionID = input("  Solution id:   ")
		if (solutionID == ""):          raise ConfigurationException("Empty input. Aborting!")
		if (solutionID in self.__repo):  raise ConfigurationException("Solution ID is already used.")

		solutionRootPath = input("  Solution path: ")
		if (solutionRootPath == ""):    raise ConfigurationException("Empty input. Aborting!")
		solutionRootPath = Path(solutionRootPath)

		if (not solutionRootPath.exists()):
			createPath = input("Path does not exists. Should it be created? [Y/n]: ")
			createPath = createPath if createPath != "" else "Y"
			if (createPath in ['n', 'N']):
				raise ConfigurationException("Cannot continue to register the new project, because '{0!s}' does not exist.".format(solutionRootPath))
			elif (createPath not in ['y', 'Y']):
				raise ConfigurationException("Unsupported choice '{0}'".format(createPath))

			try:
				solutionRootPath.mkdir(parents=True)
			except OSError as ex:
				raise ConfigurationException("Error while creating '{0!s}'.".format(solutionRootPath)) from ex

			self.__repo.AddSolution(solutionID, solutionName, solutionRootPath)
		self.__WritePoCConfiguration()
		self._LogNormal("Solution {GREEN}successfully{NOCOLOR} created.".format(**Init.Foreground))


	# ----------------------------------------------------------------------------
	# create the sub-parser for the "list-solution" command
	# ----------------------------------------------------------------------------
	@CommandGroupAttribute("Configuration commands")
	@CommandAttribute("list-solution", help="List all solutions registered in PoC.")
	def HandleListSolution(self, _): #args
		self.PrintHeadline()
		self.__PrepareForConfiguration()

		self._LogNormal("Registered solutions in PoC:")
		if self.__repo.Solutions:
			for solution in self.__repo.Solutions:
				self._LogNormal("  {id: <10}{name}".format(id=solution.ID, name=solution.Name))
				if (self.Logger.LogLevel <= Severity.Verbose):
					self._LogVerbose("  Path:   {path!s}".format(path=solution.Path))
					self._LogVerbose("  Projects:")
					for project in solution.Projects:
						self._LogVerbose("    {id: <6}{name}".format(id=project.ID, name=project.Name))
		else:
			self._LogNormal("  {RED}No registered solutions found.{NOCOLOR}".format(**Init.Foreground))

	# ----------------------------------------------------------------------------
	# create the sub-parser for the "remove-solution" command
	# ----------------------------------------------------------------------------
	@CommandGroupAttribute("Configuration commands")
	@CommandAttribute("remove-solution", help="Add a solution to PoC.")
	@ArgumentAttribute(metavar="<SolutionID>", dest="SolutionID", type=str, help="Solution name.")
	def HandleRemoveSolution(self, args):
		self.PrintHeadline()
		self.__PrepareForConfiguration()

		solution = self.__repo[args.SolutionID]

		self._LogNormal("Removing solution '{0}'.".format(solution.Name))
		remove = input("Do you really want to remove this solution? [N/y]: ")
		remove = remove if remove != "" else "N"
		if (remove in ['n', 'N']):
			raise ConfigurationException("Operation canceled.")
		elif (remove not in ['y', 'Y']):
			raise ConfigurationException("Unsupported choice '{0}'".format(remove))

		self.__repo.RemoveSolution(solution)

		self.__WritePoCConfiguration()
		self._LogNormal("Solution {GREEN}successfully{NOCOLOR} removed.".format(**Init.Foreground))


	# ----------------------------------------------------------------------------
	# create the sub-parser for the "add-project" command
	# ----------------------------------------------------------------------------
	# @CommandGroupAttribute("Configuration commands")
	# @CommandAttribute("add-project", help="Add a project to PoC.")
	# def HandleAddProject(self, args):
	# 	self.PrintHeadline()
	# 	self.__PrepareForConfiguration()

	# ----------------------------------------------------------------------------
	# create the sub-parser for the "list-project" command
	# ----------------------------------------------------------------------------
	@CommandGroupAttribute("Configuration commands")
	@CommandAttribute("list-project", help="List all projects registered in PoC.")
	def HandleListProject(self, args):
		self.PrintHeadline()
		self.__PrepareForConfiguration()

		if (args.SolutionID is None):    raise ConfigurationException("Missing command line argument '--sln'.")
		try:
			solution =  self.__repo[args.SolutionID]
		except KeyError as ex:
			raise ConfigurationException("Solution ID '{0}' is not registered in PoC.".format(args.SolutionID)) from ex

		self._LogNormal("Registered projects for solution '{0}':".format(solution.ID))
		if solution.Projects:
			for project in solution.Projects:
				self._LogNormal("  {id: <10}{name}".format(id=project.ID, name=project.Name))
		else:
			self._LogNormal("  {RED}No registered projects found.{NOCOLOR}".format(**Init.Foreground))

	# ----------------------------------------------------------------------------
	# create the sub-parser for the "remove-project" command
	# ----------------------------------------------------------------------------
	# @CommandGroupAttribute("Configuration commands")
	# @CommandAttribute("remove-project", help="Add a project to PoC.")
	# @ArgumentAttribute(metavar="<Project>", dest="Project", type=str, help="Project name.")
	# def HandleRemoveProject(self, args):
	# 	self.PrintHeadline()
	# 	self.__PrepareForConfiguration()

	# ----------------------------------------------------------------------------
	# create the sub-parser for the "add-ipcore" command
	# ----------------------------------------------------------------------------
	# @CommandGroupAttribute("Configuration commands")
	# @CommandAttribute("add-ipcore", help="Add a ipcore to PoC.")
	# def HandleAddIPCore(self, args):
	# 	self.PrintHeadline()
	# 	self.__PrepareForConfiguration()

	# ----------------------------------------------------------------------------
	# create the sub-parser for the "list-ipcore" command
	# ----------------------------------------------------------------------------
	# @CommandGroupAttribute("Configuration commands")
	# @CommandAttribute("list-ipcore", help="List all ipcores registered in PoC.")
	# def HandleListIPCore(self, args):
	# 	self.PrintHeadline()
	# 	self.__PrepareForConfiguration()
	#
	# 	ipcore = Solution(self)
	#
	# 	self._LogNormal("Registered ipcores in PoC:")
	# 	for ipcoreName in ipcore.GetIPCoreNames():
	# 		print("  {0}".format(ipcoreName))

	# ----------------------------------------------------------------------------
	# create the sub-parser for the "remove-ipcore" command
	# ----------------------------------------------------------------------------
	# @CommandGroupAttribute("Configuration commands")
	# @CommandAttribute("remove-ipcore", help="Add a ipcore to PoC.")
	# @ArgumentAttribute(metavar="<IPCore>", dest="IPCore", type=str, help="IPCore name.")
	# def HandleRemoveIPCore(self, args):
	# 	self.PrintHeadline()
	# 	self.__PrepareForConfiguration()

	# ----------------------------------------------------------------------------
	# create the sub-parser for the "add-testbench" command
	# ----------------------------------------------------------------------------
	# @CommandGroupAttribute("Configuration commands")
	# @CommandAttribute("add-testbench", help="Add a testbench to PoC.")
	# def HandleAddTestbench(self, args):
	# 	self.PrintHeadline()
	# 	self.__PrepareForConfiguration()

	# ----------------------------------------------------------------------------
	# create the sub-parser for the "remove-testbench" command
	# ----------------------------------------------------------------------------
	# @CommandGroupAttribute("Configuration commands")
	# @CommandAttribute("remove-testbench", help="Add a testbench to PoC.")
	# @ArgumentAttribute(metavar="<Testbench>", dest="Testbench", type=str, help="Testbench name.")
	# def HandleRemoveTestbench(self, args):
	# 	self.PrintHeadline()
	# 	self.__PrepareForConfiguration()

	# ----------------------------------------------------------------------------
	# create the sub-parser for the "query" command
	# ----------------------------------------------------------------------------
	@CommandGroupAttribute("Configuration commands")
	@CommandAttribute("query", help="Simulate a PoC Entity with Aldec Active-HDL")
	@ArgumentAttribute(metavar="<Query>", dest="Query", type=str, help="todo help")
	def HandleQueryConfiguration(self, args):
		self.__PrepareForConfiguration()
		query = Query(self)
		try:
			result = query.QueryConfiguration(args.Query)
			print(result, end="")
			Exit.exit()
		except ConfigurationException as ex:
			print(str(ex), end="")
			Exit.exit(1)

	# ============================================================================
	# Simulation	commands
	# ============================================================================
	# TODO: Maybe required to self-compile libraries again or in the future
	# def __PrepareVendorLibraryPaths(self):
	# 	# prepare vendor library path for Altera
	# 	if (len(self.PoCConfig.options("INSTALL.Altera.Quartus")) != 0):
	# 		self.Directories["AlteraPrimitiveSource"] = Path(self.PoCConfig['INSTALL.Altera.Quartus']['InstallationDirectory']) / "eda/sim_lib"
	# 	# prepare vendor library path for Xilinx
	# 	if (len(self.PoCConfig.options("INSTALL.Xilinx.ISE")) != 0):
	# 		self.Directories["XilinxPrimitiveSource"] = Path(self.PoCConfig['INSTALL.Xilinx.ISE']['InstallationDirectory']) / "ISE/vhdl/src"
	# 	elif (len(self.PoCConfig.options("INSTALL.Xilinx.Vivado")) != 0):
	# 		self.Directories["XilinxPrimitiveSource"] = Path(self.PoCConfig['INSTALL.Xilinx.Vivado']['InstallationDirectory']) / "data/vhdl/src"

	def _ExtractBoard(self, BoardName, DeviceName, force=False):
		if (BoardName is not None):      return Board(self, BoardName)
		elif (DeviceName is not None):  return Board(self, "Custom", DeviceName)
		elif (force is True):            raise CommonException("Either a board name or a device name is required.")
		else:                            return self.__SimulationDefaultBoard

	def _ExtractFQNs(self, fqns, defaultLibrary="PoC", defaultType=EntityTypes.Testbench):
		if (len(fqns) == 0):             raise CommonException("No FQN given.")
		return [FQN(self, fqn, defaultLibrary=defaultLibrary, defaultType=defaultType) for fqn in fqns]

	def _ExtractVHDLVersion(self, vhdlVersion, defaultVersion=None):
		if (defaultVersion is None):    defaultVersion = self.__SimulationDefaultVHDLVersion
		if (vhdlVersion is None):        return defaultVersion
		else:                            return VHDLVersion.Parse(vhdlVersion)

	# TODO: move to Configuration class in ToolChains.Xilinx.Vivado
	def _CheckVivadoEnvironment(self):
		# check if Vivado is configure
		if (len(self.PoCConfig.options("INSTALL.Xilinx.Vivado")) == 0): raise NotConfiguredException("Xilinx Vivado is not configured on this system.")
		if (environ.get('XILINX_VIVADO') is None):                      raise EnvironmentException("Xilinx Vivado environment is not loaded in this shell environment.")

	# TODO: move to Configuration class in ToolChains.Xilinx.ISE
	def _CheckISEEnvironment(self):
		# check if ISE is configure
		if (len(self.PoCConfig.options("INSTALL.Xilinx.ISE")) == 0):    raise NotConfiguredException("Xilinx ISE is not configured on this system.")
		if (environ.get('XILINX') is None):                             raise EnvironmentException("Xilinx ISE environment is not loaded in this shell environment.")

	# ----------------------------------------------------------------------------
	# create the sub-parser for the "list-testbench" command
	# ----------------------------------------------------------------------------
	@CommandGroupAttribute("Simulation commands")
	@CommandAttribute("list-testbench", help="List all testbenches")
	@PoCEntityAttribute()
	@ArgumentAttribute("--kind", metavar="<Kind>", dest="TestbenchKind", help="Testbench kind: VHDL | COCOTB")
	def HandleListTestbenches(self, args):
		self.PrintHeadline()
		self.__PrepareForSimulation()

		defaultLibrary = "PoC"

		if (args.SolutionID is not None):
			solutionName = args.SolutionID
			print("Solution name: {0}".format(solutionName))
			if self.PoCConfig.has_option("SOLUTION.Solutions", solutionName):
				sectionName = "SOLUTION.{0}".format(solutionName)
				print("Found registered solution:")
				print("  Name: {0}".format(self.PoCConfig[sectionName]['Name']))
				print("  Path: {0}".format(self.PoCConfig[sectionName]['Path']))

				solutionRootPath = self.Directories.Root / self.PoCConfig[sectionName]['Path']
				solutionConfigFile = solutionRootPath / ".PoC" / "solution.config.ini"
				solutionDefaultsFile = solutionRootPath / ".PoC" / "solution.defaults.ini"
				print("  sln files: {0!s}  {1!s}".format(solutionConfigFile, solutionDefaultsFile))

				self._LogVerbose("Reading solution file...")
				self._LogDebug("  {0!s}".format(solutionConfigFile))
				self._LogDebug("  {0!s}".format(solutionDefaultsFile))
				if not solutionConfigFile.exists():
					raise NotConfiguredException("Solution's {0} configuration file '{1!s}' does not exist.".format(solutionName, solutionConfigFile)) \
						from FileNotFoundError(str(solutionConfigFile))
				if not solutionDefaultsFile.exists():
					raise NotConfiguredException("Solution's {0} defaults file '{1!s}' does not exist.".format(solutionName, solutionDefaultsFile)) \
						from FileNotFoundError(str(solutionDefaultsFile))
				self.__pocConfig.read(str(solutionConfigFile))
				self.__pocConfig.read(str(solutionDefaultsFile))

				section =          self.PoCConfig['PROJECT.Projects']
				defaultLibrary =  section['DefaultLibrary']
				print("Solution:")
				print("  Name:            {0}".format(section['Name']))
				print("  Default library: {0}".format(defaultLibrary))
				print("  Projects:")
				for item in section:
					if (section[item] in ["PoCProject", "ISEProject", "VivadoProject", "QuartusProject"]):
						sectionName2 = "PROJECT.{0}".format(item)
						print("    {0}".format(self.PoCConfig[sectionName2]['Name']))

				print("  Namespace roots:")
				for item in section:
					if (section[item] == "Library"):
						libraryPrefix = item
						print("    {0: <16}  {1}".format(self.PoCConfig[libraryPrefix]['Name'], libraryPrefix))

						self.Root.AddLibrary(libraryPrefix, libraryPrefix)


		if (args.TestbenchKind is None):
			tbFilter =  TestbenchKind.All
		else:
			tbFilter =  TestbenchKind.Unknown
			for kind in args.TestbenchKind.lower().split(","):
				if   (kind == "vhdl"):    tbFilter |= TestbenchKind.VHDLTestbench
				elif (kind == "cocotb"):  tbFilter |= TestbenchKind.CocoTestbench
				else:                      raise CommonException("Argument --kind has an unknown value '{0}'.".format(kind))

		fqnList = self._ExtractFQNs(args.FQN, defaultLibrary)
		for fqn in fqnList:
			self._LogNormal("")
			entity = fqn.Entity
			if (isinstance(entity, WildCard)):
				for testbench in entity.GetTestbenches(tbFilter):
					print(str(testbench))
			else:
				testbench = entity.GetTestbenches(tbFilter)
				print(str(testbench))

		Exit.exit()


	# ----------------------------------------------------------------------------
	# create the sub-parser for the "asim" command
	# ----------------------------------------------------------------------------
	@CommandGroupAttribute("Simulation commands")
	@CommandAttribute("asim", help="Simulate a PoC Entity with Aldec Active-HDL")
	@PoCEntityAttribute()
	@BoardDeviceAttributeGroup()
	@VHDLVersionAttribute()
	@GUIModeAttribute()
	def HandleActiveHDLSimulation(self, args):
		self.PrintHeadline()
		self.__PrepareForSimulation()

		fqnList =      self._ExtractFQNs(args.FQN)
		board =        self._ExtractBoard(args.BoardName, args.DeviceName)
		vhdlVersion =  self._ExtractVHDLVersion(args.VHDLVersion)

		# create a GHDLSimulator instance and prepare it
		simulator = ActiveHDLSimulator(self, self.DryRun, args.GUIMode)
		allPassed = simulator.RunAll(fqnList, board=board, vhdlVersion=vhdlVersion)  # , vhdlGenerics=None)

		Exit.exit(0 if allPassed else 1)


# ----------------------------------------------------------------------------
	# create the sub-parser for the "ghdl" command
	# ----------------------------------------------------------------------------
	@CommandGroupAttribute("Simulation commands")
	@CommandAttribute("ghdl", help="Simulate a PoC Entity with GHDL")
	@PoCEntityAttribute()
	@BoardDeviceAttributeGroup()
	@VHDLVersionAttribute()
	@GUIModeAttribute()
	def HandleGHDLSimulation(self, args):
		self.PrintHeadline()
		self.__PrepareForSimulation()

		config = GHDLConfiguration(self)
		if (not config.IsSupportedPlatform()):    raise PlatformNotSupportedException()
		if (not config.IsConfigured()):            raise NotConfiguredException("GHDL is not configured on this system.")

		fqnList =      self._ExtractFQNs(args.FQN)
		board =        self._ExtractBoard(args.BoardName, args.DeviceName)
		vhdlVersion =  self._ExtractVHDLVersion(args.VHDLVersion)

		simulator = GHDLSimulator(self, self.DryRun, args.GUIMode)
		allPassed = simulator.RunAll(fqnList, board=board, vhdlVersion=vhdlVersion, guiMode=args.GUIMode)		#, vhdlGenerics=None)

		Exit.exit(0 if allPassed else 1)


	# ----------------------------------------------------------------------------
	# create the sub-parser for the "isim" command
	# ----------------------------------------------------------------------------
	@CommandGroupAttribute("Simulation commands")
	@CommandAttribute("isim", help="Simulate a PoC Entity with Xilinx ISE Simulator (iSim)")
	@PoCEntityAttribute()
	@BoardDeviceAttributeGroup()
	@GUIModeAttribute()
	def HandleISESimulation(self, args):
		self.PrintHeadline()
		self.__PrepareForSimulation()
		self._CheckISEEnvironment()

		fqnList =      self._ExtractFQNs(args.FQN)
		board =        self._ExtractBoard(args.BoardName, args.DeviceName)

		simulator = ISESimulator(self, self.DryRun, args.GUIMode)
		allPassed = simulator.RunAll(fqnList, board=board, vhdlVersion=VHDLVersion.VHDL93)		#, vhdlGenerics=None)

		Exit.exit(0 if allPassed else 1)


	# ----------------------------------------------------------------------------
	# create the sub-parser for the "vsim" command
	# ----------------------------------------------------------------------------
	@CommandGroupAttribute("Simulation commands")
	@CommandAttribute("vsim", help="Simulate a PoC Entity with Mentor QuestaSim or ModelSim (vsim)")
	@PoCEntityAttribute()
	@BoardDeviceAttributeGroup()
	@VHDLVersionAttribute()
	@GUIModeAttribute()
	def HandleQuestaSimulation(self, args):
		self.PrintHeadline()
		self.__PrepareForSimulation()

		fqnList =      self._ExtractFQNs(args.FQN)
		board =        self._ExtractBoard(args.BoardName, args.DeviceName)
		vhdlVersion =  self._ExtractVHDLVersion(args.VHDLVersion)

		simulator = QuestaSimulator(self, self.DryRun, args.GUIMode)
		allPassed = simulator.RunAll(fqnList, board=board, vhdlVersion=vhdlVersion)  # , vhdlGenerics=None)

		Exit.exit(0 if allPassed else 1)


	# ----------------------------------------------------------------------------
	# create the sub-parser for the "xsim" command
	# ----------------------------------------------------------------------------
	@CommandGroupAttribute("Simulation commands")
	@CommandAttribute("xsim", help="Simulate a PoC Entity with Xilinx Vivado Simulator (xSim)")
	@PoCEntityAttribute()
	@BoardDeviceAttributeGroup()
	@VHDLVersionAttribute()
	@GUIModeAttribute()
	def HandleVivadoSimulation(self, args):
		self.PrintHeadline()
		self.__PrepareForSimulation()

		self._CheckVivadoEnvironment()

		fqnList =      self._ExtractFQNs(args.FQN)
		board =        self._ExtractBoard(args.BoardName, args.DeviceName)
		# FIXME: VHDL-2008 is broken in Vivado 2016.1 -> use VHDL-93 by default
		vhdlVersion = self._ExtractVHDLVersion(args.VHDLVersion, defaultVersion=VHDLVersion.VHDL93)

		simulator = VivadoSimulator(self, self.DryRun, args.GUIMode)
		allPassed = simulator.RunAll(fqnList, board=board, vhdlVersion=vhdlVersion)  # , vhdlGenerics=None)

		Exit.exit(0 if allPassed else 1)


	# ----------------------------------------------------------------------------
	# create the sub-parser for the "cocotb" command
	# ----------------------------------------------------------------------------
	@CommandGroupAttribute("Simulation commands")
	@CommandAttribute("cocotb", help="Simulate a PoC Entity with Cocotb and Questa Simulator")
	@PoCEntityAttribute()
	@BoardDeviceAttributeGroup()
	@GUIModeAttribute()
	def HandleCocotbSimulation(self, args):
		self.PrintHeadline()
		self.__PrepareForSimulation()

		# check if QuestaSim is configured
		if (len(self.PoCConfig.options("INSTALL.Mentor.QuestaSim")) == 0):
			raise NotConfiguredException("Mentor QuestaSim is not configured on this system.")

		fqnList =  self._ExtractFQNs(args.FQN)
		board =    self._ExtractBoard(args.BoardName, args.DeviceName)

		# create a CocotbSimulator instance and prepare it
		simulator = CocotbSimulator(self, self.DryRun, args.GUIMode)
		allPassed = simulator.RunAll(fqnList, board=board, vhdlVersion=VHDLVersion.VHDL2008)

		Exit.exit(0 if allPassed else 1)


	# ============================================================================
	# Synthesis	commands
	# ============================================================================
	# create the sub-parser for the "list-netlist" command
	# ----------------------------------------------------------------------------
	@CommandGroupAttribute("Simulation commands")
	@CommandAttribute("list-netlist", help="List all netlists")
	@PoCEntityAttribute()
	@ArgumentAttribute("--kind", metavar="<Kind>", dest="NetlistKind", help="Netlist kind: Lattice | Quartus | XST | CoreGen")
	def HandleListNetlist(self, args):
		self.PrintHeadline()
		self.__PrepareForSynthesis()

		if (args.NetlistKind is None):
			nlFilter = NetlistKind.All
		else:
			nlFilter = NetlistKind.Unknown
			for kind in args.TestbenchKind.lower().split(","):
				if   (kind == "lattice"):  nlFilter |= NetlistKind.LatticeNetlist
				elif (kind == "quartus"):  nlFilter |= NetlistKind.QuartusNetlist
				elif (kind == "xst"):      nlFilter |= NetlistKind.XstNetlist
				elif (kind == "coregen"):  nlFilter |= NetlistKind.CoreGeneratorNetlist
				elif (kind == "vivado"):   nlFilter |= NetlistKind.VivadoNetlist
				else:                      raise CommonException("Argument --kind has an unknown value '{0}'.".format(kind))

		fqnList = self._ExtractFQNs(args.FQN)
		for fqn in fqnList:
			entity = fqn.Entity
			if (isinstance(entity, WildCard)):
				for testbench in entity.GetNetlists(nlFilter):
					print(str(testbench))
			else:
				testbench = entity.GetNetlists(nlFilter)
				print(str(testbench))

		Exit.exit()

	# ----------------------------------------------------------------------------
	# create the sub-parser for the "coregen" command
	# ----------------------------------------------------------------------------
	@CommandGroupAttribute("Synthesis commands")
	@CommandAttribute("coregen", help="Generate an IP core with Xilinx ISE Core Generator")
	@PoCEntityAttribute()
	@BoardDeviceAttributeGroup()
	@NoCleanUpAttribute()
	def HandleCoreGeneratorCompilation(self, args):
		self.PrintHeadline()
		self.__PrepareForSynthesis()
		self._CheckISEEnvironment()

		fqnList =  self._ExtractFQNs(args.FQN, defaultType=EntityTypes.NetList)
		board =    self._ExtractBoard(args.BoardName, args.DeviceName, force=True)

		compiler = XCOCompiler(self, self.DryRun, args.NoCleanUp)
		compiler.RunAll(fqnList, board)

		Exit.exit()

	# ----------------------------------------------------------------------------
	# create the sub-parser for the "xst" command
	# ----------------------------------------------------------------------------
	@CommandGroupAttribute("Synthesis commands")
	@CommandAttribute("xst", help="Compile a PoC IP core with Xilinx ISE XST to a netlist")
	@PoCEntityAttribute()
	@BoardDeviceAttributeGroup()
	@NoCleanUpAttribute()
	def HandleXstCompilation(self, args):
		self.PrintHeadline()
		self.__PrepareForSynthesis()
		self._CheckISEEnvironment()

		fqnList =  self._ExtractFQNs(args.FQN, defaultType=EntityTypes.NetList)
		board =    self._ExtractBoard(args.BoardName, args.DeviceName, force=True)

		compiler = XSTCompiler(self, self.DryRun, args.NoCleanUp)
		compiler.RunAll(fqnList, board)

		Exit.exit()

	# ----------------------------------------------------------------------------
	# create the sub-parser for the "vivado" command
	# ----------------------------------------------------------------------------
	@CommandGroupAttribute("Synthesis commands")
	@CommandAttribute("vivado", help="Compile a PoC IP core with Xilinx Vivado Synth to a design checkpoint")
	@PoCEntityAttribute()
	@BoardDeviceAttributeGroup()
	@NoCleanUpAttribute()
	def HandleVivadoCompilation(self, args):
		self.PrintHeadline()
		self.__PrepareForSynthesis()
		self._CheckVivadoEnvironment()

		fqnList =  self._ExtractFQNs(args.FQN, defaultType=EntityTypes.NetList)
		board =    self._ExtractBoard(args.BoardName, args.DeviceName, force=True)

		compiler = VivadoCompiler(self, self.DryRun, args.NoCleanUp)
		compiler.RunAll(fqnList, board)

		Exit.exit()


	# ----------------------------------------------------------------------------
	# create the sub-parser for the "quartus" command
	# ----------------------------------------------------------------------------
	@CommandGroupAttribute("Synthesis commands")
	@CommandAttribute("quartus", help="Compile a PoC IP core with Altera Quartus II Map to a netlist")
	@PoCEntityAttribute()
	@BoardDeviceAttributeGroup()
	@NoCleanUpAttribute()
	def HandleQuartusCompilation(self, args):
		self.PrintHeadline()
		self.__PrepareForSynthesis()

		# TODO: check env variables
		# self._CheckQuartusEnvironment()

		fqnList =  self._ExtractFQNs(args.FQN, defaultType=EntityTypes.NetList)
		board =    self._ExtractBoard(args.BoardName, args.DeviceName, force=True)

		compiler = MapCompiler(self, self.DryRun, args.NoCleanUp)
		compiler.RunAll(fqnList, board)

		Exit.exit()


	# ----------------------------------------------------------------------------
	# create the sub-parser for the "lattice" command
	# ----------------------------------------------------------------------------
	@CommandGroupAttribute("Synthesis commands")
	@CommandAttribute("lse", help="Compile a PoC IP core with Lattice Diamond LSE to a netlist")
	@PoCEntityAttribute()
	@BoardDeviceAttributeGroup()
	@NoCleanUpAttribute()
	def HandleLSECompilation(self, args):
		self.PrintHeadline()
		self.__PrepareForSynthesis()

		# TODO: check env variables
		# self._CheckLatticeEnvironment()

		fqnList =  self._ExtractFQNs(args.FQN, defaultType=EntityTypes.NetList)
		board =    self._ExtractBoard(args.BoardName, args.DeviceName, force=True)

		compiler = LSECompiler(self, self.DryRun, args.NoCleanUp)
		compiler.RunAll(fqnList, board)

		Exit.exit()


# main program
def main():
	dryRun =  "-D" in sys_argv
	debug =   "-d" in sys_argv
	verbose = "-v" in sys_argv
	quiet =   "-q" in sys_argv

	# configure Exit class
	Exit.quiet = quiet

	try:
		Init.init()
		# handover to a class instance
		poc = PoC(debug, verbose, quiet, dryRun)
		poc.Run()
		Exit.exit()

	except (CommonException, ConfigurationException, SimulatorException, CompilerException) as ex:
		print("{RED}ERROR:{NOCOLOR} {message}".format(message=ex.message, **Init.Foreground))
		cause = ex.__cause__
		if isinstance(cause, FileNotFoundError):
			print("{YELLOW}  FileNotFound:{NOCOLOR} '{cause}'".format(cause=str(cause), **Init.Foreground))
		elif isinstance(cause, NotADirectoryError):
			print("{YELLOW}  NotADirectory:{NOCOLOR} '{cause}'".format(cause=str(cause), **Init.Foreground))
		elif isinstance(cause, DuplicateOptionError):
			print("{YELLOW}  DuplicateOptionError:{NOCOLOR} '{cause}'".format(cause=str(cause), **Init.Foreground))
		elif isinstance(cause, ConfigParser_Error):
			print("{YELLOW}  configparser.Error:{NOCOLOR} '{cause}'".format(cause=str(cause), **Init.Foreground))
		elif isinstance(cause, ParserException):
			print("{YELLOW}  ParserException:{NOCOLOR} {cause}".format(cause=str(cause), **Init.Foreground))
			cause = cause.__cause__
			if (cause is not None):
				print("{YELLOW}    {name}:{NOCOLOR} {cause}".format(name=cause.__class__.__name__, cause= str(cause), **Init.Foreground))
		elif isinstance(cause, ToolChainException):
			print("{YELLOW}  {name}:{NOCOLOR} {cause}".format(name=cause.__class__.__name__, cause=str(cause), **Init.Foreground))
			cause = cause.__cause__
			if (cause is not None):
				if isinstance(cause, OSError):
					print("{YELLOW}    {name}:{NOCOLOR} {cause}".format(name=cause.__class__.__name__, cause=str(cause), **Init.Foreground))
			else:
				print("  Possible causes:")
				print("   - The compile order is broken.")
				print("   - A source file was not compiled and an old file got used.")

		if (not (verbose or debug)):
			print()
			print("{CYAN}  Use '-v' for verbose or '-d' for debug to print out extended messages.{NOCOLOR}".format(**Init.Foreground))
		Exit.exit(1)

	except EnvironmentException as ex:          Exit.printEnvironmentException(ex)
	except NotConfiguredException as ex:        Exit.printNotConfiguredException(ex)
	except PlatformNotSupportedException as ex: Exit.printPlatformNotSupportedException(ex)
	except ExceptionBase as ex:                 Exit.printExceptionbase(ex)
	except NotImplementedError as ex:           Exit.printNotImplementedError(ex)
	except Exception as ex:                     Exit.printException(ex)

# entry point
if __name__ == "__main__":
	Exit.versionCheck((3,5,0))
	main()
else:
	Exit.printThisIsNoLibraryFile(PoC.HeadLine)
