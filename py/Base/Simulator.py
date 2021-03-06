# EMACS settings: -*-	tab-width: 2; indent-tabs-mode: t; python-indent-offset: 2 -*-
# vim: tabstop=2:shiftwidth=2:noexpandtab
# kate: tab-width 2; replace-tabs off; indent-width 2;
# 
# ==============================================================================
# Authors:          Patrick Lehmann
#                   Martin Zabel
# 
# Python Class:      TODO
# 
# Description:
# ------------------------------------
#		TODO:
#		- 
#		- 
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
#   http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
#
# entry point
if __name__ != "__main__":
	pass
	# place library initialization code here
else:
	from lib.Functions import Exit
	Exit.printThisIsNoExecutableFile("PoC Library - Python Module Simulator.Base")


# load dependencies
from datetime           import datetime
from enum               import Enum, unique

from lib.Functions      import Init
from Base.Exceptions    import ExceptionBase, SkipableException
from Base.Logging       import LogEntry
from Base.Project       import Environment, VHDLVersion
from Base.Shared        import Shared
from PoC.Entity         import WildCard
from PoC.TestCase       import TestSuite, TestCase, Status


VHDL_TESTBENCH_LIBRARY_NAME = "test"


class SimulatorException(ExceptionBase):
	pass

class SkipableSimulatorException(SimulatorException, SkipableException):
	pass


@unique
class SimulationState(Enum):
	Prepare =     0
	Analyze =     1
	Elaborate =   2
	Optimize =    3
	Simulate =    4
	View =        5

@unique
class SimulationResult(Enum):
	NotRun =      0
	Error =       1
	Failed =      2
	NoAsserts =   3
	Passed =      4

# local helper function
def to_time(seconds):
	"""Convert n seconds to a str with pattern {min}:{sec:02}."""
	minutes = int(seconds / 60)
	seconds = seconds - (minutes * 60)
	return "{min}:{sec:02}".format(min=minutes, sec=seconds)


class Simulator(Shared):
	_ENVIRONMENT = Environment.Simulation

	class __Directories__(Shared.__Directories__):
		PreCompiled = None

	def __init__(self, host, dryRun):
		super().__init__(host, dryRun)

		self._vhdlVersion = VHDLVersion.VHDL2008
		self._testSuite =   TestSuite()			# TODO: This includes not the read ini files phases ...

		self._state =           SimulationState.Prepare
		self._startAt =         datetime.now()
		self._endAt =           None
		self._lastEvent =       self._startAt
		self._prepareTime =     None
		self._analyzeTime =     None
		self._elaborationTime = None
		self._simulationTime =  None


	# class properties
	# ============================================================================
	@property
	def TestSuite(self):      return self._testSuite

	def _GetTimeDeltaSinceLastEvent(self):
		now = datetime.now()
		result = now - self._lastEvent
		self._lastEvent = now
		return result

	def _PrepareSimulationEnvironment(self):
		self._LogNormal("Preparing simulation environment...")
		self._PrepareEnvironment()

	def RunAll(self, fqnList, *args, **kwargs):
		"""Run a list of testbenches. Expand wildcards to all selected testbenches."""
		self._testSuite.StartTimer()
		try:
			for fqn in fqnList:
				entity = fqn.Entity
				if (isinstance(entity, WildCard)):
					for testbench in entity.GetVHDLTestbenches():
						self.TryRun(testbench, *args, **kwargs)
				else:
					testbench = entity.VHDLTestbench
					self.TryRun(testbench, *args, **kwargs)
		except KeyboardInterrupt:
			self._LogError("Received a keyboard interrupt.")
		finally:
			self._testSuite.StopTimer()

		self.PrintOverallSimulationReport()

		return self._testSuite.IsAllPassed

	def TryRun(self, testbench, *args, **kwargs):
		"""Try to run a testbench. Skip skipable exceptions by printing the error and its cause."""
		__SIMULATION_STATE_TO_TESTCASE_STATUS__ = {
			SimulationState.Prepare: Status.InternalError,
			SimulationState.Analyze: Status.AnalyzeError,
			SimulationState.Elaborate: Status.ElaborationError,
			SimulationState.Optimize: Status.ElaborationError,
			SimulationState.Simulate: Status.SimulationError
		}

		testCase = TestCase(testbench)
		self._testSuite.AddTestCase(testCase)
		testCase.StartTimer()
		try:
			self.Run(testbench, *args, **kwargs)
			testCase.UpdateStatus(testbench.Result)
		except SkipableSimulatorException as ex:
			testCase.Status = __SIMULATION_STATE_TO_TESTCASE_STATUS__[self._state]

			self._LogQuiet("  {RED}ERROR:{NOCOLOR} {ExMsg}".format(ExMsg=ex.message, **Init.Foreground))
			cause = ex.__cause__
			if (cause is not None):
				self._LogQuiet("    {YELLOW}{ExType}:{NOCOLOR} {ExMsg!s}".format(ExType=cause.__class__.__name__, ExMsg=cause, **Init.Foreground))
				cause = cause.__cause__
				if (cause is not None):
					self._LogQuiet("      {YELLOW}{ExType}:{NOCOLOR} {ExMsg!s}".format(ExType=cause.__class__.__name__, ExMsg=cause, **Init.Foreground))
			self._LogQuiet("  {RED}[SKIPPED DUE TO ERRORS]{NOCOLOR}".format(**Init.Foreground))
		except SimulatorException:
			testCase.Status = __SIMULATION_STATE_TO_TESTCASE_STATUS__[self._state]
			raise
		except ExceptionBase:
			testCase.Status = Status.SystemError
			raise
		finally:
			testCase.StopTimer()

	def Run(self, testbench, board, vhdlVersion, vhdlGenerics=None, guiMode=False):
		"""Write the Testbench message line, create a PoCProject and add the first *.files file to it."""
		self._LogQuiet("{CYAN}Testbench:{NOCOLOR} {0!s}".format(testbench.Parent, **Init.Foreground))

		self._vhdlVersion =  vhdlVersion
		self._vhdlGenerics = vhdlGenerics

		# setup all needed paths to execute fuse
		self._CreatePoCProject(testbench.ModuleName, board)
		self._AddFileListFile(testbench.FilesFile)

		self._prepareTime = self._GetTimeDeltaSinceLastEvent()

		self._LogNormal("Running analysis for every vhdl file...")
		self._state = SimulationState.Analyze
		self._RunAnalysis(testbench)
		self._analyzeTime = self._GetTimeDeltaSinceLastEvent()

		self._LogNormal("Running elaboration...")
		self._state = SimulationState.Elaborate
		self._RunElaboration(testbench)
		self._elaborationTime = self._GetTimeDeltaSinceLastEvent()

		self._LogNormal("Running simulation...")
		self._state = SimulationState.Simulate
		self._RunSimulation(testbench)
		self._simulationTime = self._GetTimeDeltaSinceLastEvent()

		if (guiMode is True):
			self._LogNormal("Executing waveform viewer...")
			self._state = SimulationState.View
			self._RunView(testbench)

		self._endAt = datetime.now()

	def _RunAnalysis(self, testbench):
		pass

	def _RunElaboration(self, testbench):
		pass

	def _RunSimulation(self, testbench):
		pass

	def _RunView(self, testbench):
		pass

	def PrintOverallSimulationReport(self):
		self._LogQuiet("{HEADLINE}{line}{NOCOLOR}".format(line="=" * 80, **Init.Foreground))
		self._LogQuiet("{HEADLINE}{headline: ^80s}{NOCOLOR}".format(headline="Overall Simulation Report", **Init.Foreground))
		self._LogQuiet("{HEADLINE}{line}{NOCOLOR}".format(line="=" * 80, **Init.Foreground))
		# table header
		self._LogQuiet("{Name: <24} | {Duration: >5} | {Status: ^11}".format(Name="Name", Duration="Time", Status="Status"))
		self._LogQuiet("-" * 80)
		self.PrintSimulationReportLine(self._testSuite, 0, 24)

		self._LogQuiet("{HEADLINE}{line}{NOCOLOR}".format(line="=" * 80, **Init.Foreground))
		self._LogQuiet("Time: {time: >5}  Count: {count: <3}  Passed: {passed: <3}  No Asserts: {noassert: <2}  Failed: {failed: <2}  Errors: {error: <2}".format(
			time=to_time(self._testSuite.OverallRunTime),
			count=self._testSuite.Count,
			passed=self._testSuite.PassedCount,
			noassert=self._testSuite.NoAssertsCount,
			failed=self._testSuite.FailedCount,
			error=self._testSuite.ErrorCount
		))
		self._LogQuiet("{HEADLINE}{line}{NOCOLOR}".format(line="=" * 80, **Init.Foreground))

	__SIMULATION_REPORT_COLOR_TABLE__ = {
		Status.Unknown:             "RED",
		Status.InternalError:				"DARK_RED",
		Status.SystemError:         "DARK_RED",
		Status.AnalyzeError:        "DARK_RED",
		Status.ElaborationError:    "DARK_RED",
		Status.SimulationError:     "RED",
		Status.SimulationFailed:    "RED",
		Status.SimulationNoAsserts: "YELLOW",
		Status.SimulationSuccess:   "GREEN"
	}

	__SIMULATION_REPORT_STATUS_TEXT_TABLE__ = {
		Status.Unknown:             "-- ?? --",
		Status.InternalError:				"INT. ERROR",
		Status.SystemError:         "SYS. ERROR",
		Status.AnalyzeError:        "ANA. ERROR",
		Status.ElaborationError:    "ELAB. ERROR",
		Status.SimulationError:     "SIM. ERROR",
		Status.SimulationFailed:    "FAILED",
		Status.SimulationNoAsserts: "NO ASSERTS",
		Status.SimulationSuccess:   "PASSED"
	}

	def PrintSimulationReportLine(self, testObject, indent, nameColumnWidth):
		_indent = "  " * indent
		for group in testObject.TestGroups.values():
			pattern = "{indent}{{groupName: <{nameColumnWidth}}} |       | ".format(indent=_indent, nameColumnWidth=nameColumnWidth)
			self._LogQuiet(pattern.format(groupName=group.Name))
			self.PrintSimulationReportLine(group, indent + 1, nameColumnWidth - 2)
		for testCase in testObject.TestCases.values():
			pattern = "{indent}{{testcaseName: <{nameColumnWidth}}} | {{duration: >5}} | {{{color}}}{{status: ^11}}{{NOCOLOR}}".format(
				indent=_indent, nameColumnWidth=nameColumnWidth, color=self.__SIMULATION_REPORT_COLOR_TABLE__[testCase.Status])
			self._LogQuiet(pattern.format(testcaseName=testCase.Name, duration=to_time(testCase.OverallRunTime),
																		status=self.__SIMULATION_REPORT_STATUS_TEXT_TABLE__[testCase.Status], **Init.Foreground))


def PoCSimulationResultFilter(gen, simulationResult):
	state = 0
	for line in gen:
		if   ((state == 0) and (line.Message == "========================================")):
			state += 1
		elif ((state == 1) and (line.Message == "POC TESTBENCH REPORT")):
			state += 1
		elif ((state == 2) and (line.Message == "========================================")):
			state += 1
		elif ((state == 3) and (line.Message == "========================================")):
			state += 1
		elif ((state == 4) and line.Message.startswith("SIMULATION RESULT = ")):
			state += 1
			if line.Message.endswith("FAILED"):
				color = Init.Foreground['RED']
				simulationResult <<= SimulationResult.Failed
			elif line.Message.endswith("NO ASSERTS"):
				color = Init.Foreground['YELLOW']
				simulationResult <<= SimulationResult.NoAsserts
			elif line.Message.endswith("PASSED"):
				color = Init.Foreground['GREEN']
				simulationResult <<= SimulationResult.Passed
			else:
				color = Init.Foreground['RED']
				simulationResult <<= SimulationResult.Error

			yield LogEntry("{COLOR}{line}{NOCOLOR}".format(COLOR=color,line=line.Message, **Init.Foreground), line.Severity, line.Indent)
			continue
		elif ((state == 5) and (line.Message == "========================================")):
			state += 1

		yield line

	if (state != 6):    raise SkipableSimulatorException("No PoC Testbench Report in simulator output found.")
