
import guiplugins, plugins, os, sys, shutil, time, subprocess, operator, types, logging
from copy import copy, deepcopy
from threading import Thread
from glob import glob
from stat import *
from ndict import seqdict
from string import Template

try:
    import gtk, helpdialogs
except ImportError:
    pass # don't fail on scripts : we should already have imported it anyway


class Quit(guiplugins.BasicActionGUI):
    def __init__(self, *args):
        guiplugins.BasicActionGUI.__init__(self, *args)
        self.annotation = ""
    def _getStockId(self):
        return "quit"
    def _getTitle(self):
        return "_Quit"
    def isActiveOnCurrent(self, *args):
        return True
    def getSignalsSent(self):
        return [ "Quit" ]
    def performOnCurrent(self):
        self.notify("Quit")
    def notifyAnnotate(self, annotation):
        self.annotation = annotation
    def messageAfterPerform(self):
        pass # GUI isn't there to show it
    def getConfirmationMessage(self):
        message = ""
        if self.annotation:
            message = "You annotated this GUI, using the following message : \n" + self.annotation + "\n"
        runningProcesses = guiplugins.processMonitor.listRunningProcesses()
        if len(runningProcesses) > 0:
            message += "\nThese processes are still running, and will be terminated when quitting: \n\n   + " + \
                       "\n   + ".join(runningProcesses) + "\n"
        if message:
            message += "\nQuit anyway?\n"
        return message


# Plugin for saving tests (standard)
class SaveTests(guiplugins.ActionDialogGUI):
    def __init__(self, allApps, *args):
        guiplugins.ActionDialogGUI.__init__(self, allApps, *args)
        self.directAction = gtk.Action("Save", "_Save", \
                                       self.getDirectTooltip(), self.getStockId())
        guiplugins.scriptEngine.connect(self.getDirectTooltip(), "activate", self.directAction, self._respond)
        self.directAction.set_property("sensitive", False)
        self.addOption("v", "Version to save")
        self.addOption("old", "Version to save previous results as")
        self.addSwitch("over", "Replace successfully compared files also", 0)
        if self.hasPerformance(allApps):
            self.addSwitch("ex", "Save", 1, ["Average performance", "Exact performance"])

    def getDialogTitle(self):
        stemsToSave = self.getStemsToSave()
        saveDesc = "Saving " + str(len(self.currTestSelection)) + " tests"
        if len(stemsToSave) > 0:
            saveDesc += ", only files " + ",".join(stemsToSave)
        return saveDesc

    def _getStockId(self):
        return "save"
    def _getTitle(self):
        return "Save _As..."
    def getTooltip(self):
        return "Save results with non-default settings"
    def getDirectTooltip(self):
        return "Save results for selected tests"
    def messageAfterPerform(self):
        pass # do it in the method

    def addToGroups(self, actionGroup, accelGroup):
        self.directAccel = self._addToGroups("Save", self.directAction, actionGroup, accelGroup)
        guiplugins.ActionDialogGUI.addToGroups(self, actionGroup, accelGroup)

    def describeAction(self):
        self._describeAction(self.directAction, self.directAccel)
        self._describeAction(self.gtkAction, self.accelerator)

    def setSensitivity(self, newValue):
        self._setSensitivity(self.directAction, newValue)
        self._setSensitivity(self.gtkAction, newValue)
        if newValue:
            self.updateOptions()

    def getConfirmationMessage(self):
        testsForWarn = filter(lambda test: test.state.warnOnSave(), self.currTestSelection)
        if len(testsForWarn) == 0:
            return ""
        message = "You have selected tests whose results are partial or which are registered as bugs:\n"
        for test in testsForWarn:
            message += "  Test '" + test.uniqueName + "' " + test.state.categoryRepr() + "\n"
        message += "Are you sure you want to do this?\n"
        return message

    def getSaveableTests(self):
        return filter(lambda test: test.state.isSaveable(), self.currTestSelection)
    def updateOptions(self):
        defaultSaveOption = self.getDefaultSaveOption()
        versionOption = self.optionGroup.getOption("v")
        currOption = versionOption.defaultValue
        newVersions = self.getPossibleVersions()
        currVersions = versionOption.possibleValues
        if defaultSaveOption == currOption and newVersions == currVersions:
            return False
        self.optionGroup.setOptionValue("v", defaultSaveOption)
        self.diag.info("Setting default save version to " + defaultSaveOption)
        self.optionGroup.setPossibleValues("v", newVersions)
        return True
    def getDefaultSaveOption(self):
        saveVersions = self.getSaveVersions()
        if saveVersions.find(",") != -1:
            return "<default> - " + saveVersions
        else:
            return saveVersions
    def getPossibleVersions(self):
        extensions = []
        for app in self.currAppSelection:
            for ext in app.getSaveableVersions():
                if not ext in extensions:
                    extensions.append(ext)
        # Include the default version always
        extensions.append("")
        return extensions
    def getSaveVersions(self):
        if self.isAllNew():
            return ""

        saveVersions = []
        for app in self.currAppSelection:
            ver = self.getDefaultSaveVersion(app)
            if not ver in saveVersions:
                saveVersions.append(ver)
        return ",".join(saveVersions)
    def getDefaultSaveVersion(self, app):
        return app.getFullVersion(forSave = 1)
    def hasPerformance(self, apps):
        for app in apps:
            if app.hasPerformance():
                return True
        return False
    def getExactness(self):
        return int(self.optionGroup.getSwitchValue("ex", 1))
    def isAllNew(self):
        for test in self.getSaveableTests():
            if not test.state.isAllNew():
                return False
        return True
    def getVersion(self, test):
        versionString = self.optionGroup.getOptionValue("v")
        if versionString.startswith("<default>"):
            return self.getDefaultSaveVersion(test.app)
        else:
            return versionString
    def isActiveOnCurrent(self, test=None, state=None):
        if state and state.isSaveable():
            return True
        for seltest in self.currTestSelection:
            if seltest is not test and seltest.state.isSaveable():
                return True
        return False
    def getStemsToSave(self):
        return [ os.path.basename(fileName).split(".")[0] for fileName, comparison in self.currFileSelection ]
    def performOnCurrent(self):
        backupVersion = self.optionGroup.getOptionValue("old")
        if backupVersion and backupVersion == self.optionGroup.getOptionValue("v"):
            raise plugins.TextTestError, "Cannot backup to the same version we're trying to save! Choose another name."
        
        saveDesc = ", exactness " + str(self.getExactness())
        stemsToSave = self.getStemsToSave()
        if len(stemsToSave) > 0:
            saveDesc += ", only " + ",".join(stemsToSave)
        overwriteSuccess = self.optionGroup.getSwitchValue("over")
        if overwriteSuccess:
            saveDesc += ", overwriting both failed and succeeded files"

        tests = self.getSaveableTests()
        # Calculate the versions beforehand, as saving tests can change the selection,
        # which can affect the default version calculation...
        testsWithVersions = [ (test, self.getVersion(test)) for test in tests ]
        testDesc = str(len(tests)) + " tests"
        self.notify("Status", "Saving " + testDesc + " ...")
        try:
            for test, version in testsWithVersions:
                guiplugins.guilog.info("Saving " + repr(test) + " - version " + version + saveDesc)
                testComparison = test.state
                testComparison.setObservers(self.observers)
                testComparison.save(test, self.getExactness(), version, overwriteSuccess, stemsToSave, backupVersion)
                newState = testComparison.makeNewState(test.app, "saved")
                test.changeState(newState)

            self.notify("Status", "Saved " + testDesc + ".")
        except OSError, e:
            self.notify("Status", "Failed to save " + testDesc + ".")
            errorStr = str(e)
            if errorStr.find("Permission") != -1:
                raise plugins.TextTestError, "Failed to save " + testDesc + \
                      " : didn't have sufficient write permission to the test files"
            else:
                raise plugins.TextTestError, errorStr


class MarkTest(guiplugins.ActionDialogGUI):
    def __init__(self, *args):
        guiplugins.ActionDialogGUI.__init__(self, *args)
        self.addOption("brief", "Brief text", "Checked")
        self.addOption("free", "Free text", "Checked at " + plugins.localtime())
    def _getTitle(self):
        return "_Mark"
    def getTooltip(self):
        return "Mark the selected tests"
    def performOnCurrent(self):
        for test in self.currTestSelection:
            oldState = test.state
            if oldState.isComplete():
                if test.state.isMarked():
                    oldState = test.state.oldState # Keep the old state so as not to build hierarchies ...
                newState = plugins.MarkedTestState(self.optionGroup.getOptionValue("free"),
                                                   self.optionGroup.getOptionValue("brief"), oldState)
                test.changeState(newState)
                self.notify("ActionProgress", "") # Just to update gui ...
    def isActiveOnCurrent(self, test=None, state=None):
        if state and state.isComplete():
            return True
        for seltest in self.currTestSelection:
            if seltest is not test and seltest.state.isComplete():
                return True
        return False

class UnmarkTest(guiplugins.ActionGUI):
    def _getTitle(self):
        return "_Unmark"
    def getTooltip(self):
        return "Unmark the selected tests"
    def performOnCurrent(self):
        for test in self.currTestSelection:
            if test.state.isMarked():
                test.state.oldState.lifecycleChange = "unmarked" # To avoid triggering completion ...
                test.changeState(test.state.oldState)
                self.notify("ActionProgress", "") # Just to update gui ...
    def isActiveOnCurrent(self, *args):
        for test in self.currTestSelection:
            if test.state.isMarked():
                return True
        return False

class FileViewAction(guiplugins.ActionGUI):
    def singleTestOnly(self):
        return True

    def isActiveOnCurrent(self, *args):
        if not guiplugins.ActionGUI.isActiveOnCurrent(self):
            return False
        for fileName, obj in self.currFileSelection:
            if self.isActiveForFile(fileName, obj):
                return True
        return False

    def isActiveForFile(self, fileName, *args):
        return fileName and not os.path.isdir(fileName)

    def useFiltered(self):
        return False

    def performOnCurrent(self):
        for fileName, associatedObject in self.currFileSelection:
            if self.isActiveForFile(fileName, associatedObject):
                self.performOnFile(fileName, associatedObject)

    def performOnFile(self, fileName, associatedObject):
        fileToView = self.getFileToView(fileName, associatedObject)
        if os.path.isfile(fileToView) or os.path.islink(fileToView):
            viewTool = self.getViewToolName(fileToView)
            if viewTool:
                try:
                    self._performOnFile(viewTool, fileToView, associatedObject)
                except OSError:
                    self.showErrorDialog("Cannot find " + self.getToolDescription() + " '" + viewTool + \
                                         "'.\nPlease install it somewhere on your PATH or\n"
                                         "change the configuration entry '" + self.getToolConfigEntry() + "'.")
            else:
                self.showWarningDialog("No " + self.getToolDescription() + " is defined for files of type '" + \
                                       os.path.basename(fileToView).split(".")[0] + \
                                       "'.\nPlease point the configuration entry '" + self.getToolConfigEntry() + "'"
                                       " at a valid program to view the file.")
        else:
            self.showErrorDialog("File '" + os.path.basename(fileName) + "' cannot be viewed"
                                 " as it has been removed in the file system." + self.noFileAdvice())

    def isDefaultViewer(self, *args):
        return False

    def notifyViewFile(self, fileName, *args):
        if self.isDefaultViewer(*args):
            self.performOnFile(fileName, *args)

    def getFileToView(self, fileName, associatedObject):
        try:
            # associatedObject might be a comparison object, but it might not
            # Use the comparison if it's there
            return associatedObject.existingFile(self.useFiltered())
        except AttributeError:
            return fileName
    def noFileAdvice(self):
        if len(self.currAppSelection) > 0:
            return "\n" + self.currAppSelection[0].noFileAdvice()
        else:
            return ""
    def testDescription(self):
        if len(self.currTestSelection) > 0:
            return " (from test " + self.currTestSelection[0].uniqueName + ")"
        else:
            return ""
    def getRemoteHost(self):
        if os.name == "posix" and len(self.currTestSelection) > 0:
            state = self.currTestSelection[0].state
            if hasattr(state, "executionHosts") and len(state.executionHosts) > 0:
                remoteHost = state.executionHosts[0]
                localhost = plugins.gethostname()
                if remoteHost != localhost:
                    return remoteHost

    def getFullDisplay(self):
        display = os.getenv("DISPLAY", "")
        if display.startswith(":"):
            return plugins.gethostname() + display
        else:
            return display.replace("localhost", plugins.gethostname())

    def getSignalsSent(self):
        return [ "ViewerStarted" ]
    def startViewer(self, cmdArgs, description, *args, **kwargs):
        testDesc = self.testDescription()
        fullDesc = description + testDesc
        nullFile = open(os.devnull, "w")
        guiplugins.processMonitor.startProcess(cmdArgs, fullDesc, stdout=nullFile, stderr=nullFile, *args, **kwargs)
        self.notify("Status", 'Started "' + description + '" in background' + testDesc + '.')
        self.notify("ViewerStarted")

    def getStem(self, fileName):
        return os.path.basename(fileName).split(".")[0]
    def testRunning(self):
        return self.currTestSelection[0].state.hasStarted() and \
               not self.currTestSelection[0].state.isComplete()

    def getViewToolName(self, fileName):
        stem = self.getStem(fileName)
        if len(self.currTestSelection) > 0:
            return self.currTestSelection[0].getCompositeConfigValue(self.getToolConfigEntry(), stem)
        else:
            return guiplugins.guiConfig.getCompositeValue(self.getToolConfigEntry(), stem)
    def differencesActive(self, comparison):
        if not comparison or comparison.newResult() or comparison.missingResult():
            return False
        return comparison.hasDifferences()
    def messageAfterPerform(self):
        pass # provided by starting viewer, with message


class ViewInEditor(FileViewAction):
    def __init__(self, allApps, dynamic):
        FileViewAction.__init__(self, allApps)
        self.dynamic = dynamic

    def _getStockId(self):
        return "open"

    def getToolConfigEntry(self):
        return "view_program"

    def getToolDescription(self):
        return "file viewing program"

    def viewFile(self, fileName, viewTool, exitHandler, exitHandlerArgs):
        cmdArgs, descriptor, env = self.getViewCommand(fileName, viewTool)
        description = descriptor + " " + os.path.basename(fileName)
        refresh = str(exitHandler != self.editingComplete)
        guiplugins.guilog.info("Viewing file " + fileName + " using '" + descriptor + "', refresh set to " + refresh)
        self.startViewer(cmdArgs, description=description, env=env,
                         exitHandler=exitHandler, exitHandlerArgs=exitHandlerArgs)
    def getViewerEnvironment(self, cmdArgs):
        # An absolute path to the viewer may indicate a custom tool, send the test environment along too
        # Doing this is unlikely to cause harm in any case
        if len(self.currTestSelection) > 0 and os.path.isabs(cmdArgs[0]):
            return self.currTestSelection[0].getRunEnvironment()

    def getViewCommand(self, fileName, viewProgram):
        # viewProgram might have arguments baked into it...
        cmdArgs = plugins.splitcmd(viewProgram) + [ fileName ]
        program = cmdArgs[0]
        descriptor = " ".join([ os.path.basename(program) ] + cmdArgs[1:-1])
        env = self.getViewerEnvironment(cmdArgs)
        interpreter = plugins.getInterpreter(program)
        if interpreter:
            cmdArgs = [ interpreter ] + cmdArgs

        if guiplugins.guiConfig.getCompositeValue("view_file_on_remote_machine", self.getStem(fileName)):
            remoteHost = self.getRemoteHost()
            if remoteHost:
                remoteShellProgram = guiplugins.guiConfig.getValue("remote_shell_program")
                cmdArgs = [ remoteShellProgram, remoteHost, "env DISPLAY=" + self.getFullDisplay() + " " + " ".join(cmdArgs) ]

        return cmdArgs, descriptor, env

    def _performOnFile(self, viewTool, fileName, *args):
        exitHandler, exitHandlerArgs = self.findExitHandlerInfo(fileName, *args)
        return self.viewFile(fileName, viewTool, exitHandler, exitHandlerArgs)

    def editingComplete(self):
        guiplugins.scriptEngine.applicationEvent("file editing operations to complete")


class ViewConfigFileInEditor(ViewInEditor):
    def __init__(self, *args):
        ViewInEditor.__init__(self, *args)
        self.rootTestSuites = []

    def _getTitle(self):
        return "View In Editor"

    def addSuites(self, suites):
        ViewInEditor.addSuites(self, suites)
        self.rootTestSuites += suites

    def isActiveOnCurrent(self, *args):
        return False # only way to get at it is via the activation below...

    def notifyViewApplicationFile(self, fileName, apps):
        self.performOnFile(fileName, apps)

    def findExitHandlerInfo(self, fileName, apps):
        return self.configFileChanged, (apps,)

    def configFileChanged(self, apps):
        for app in apps:
            app.setUpConfiguration()
            suite = self.findSuite(app)
            self.refreshFilesRecursively(suite)

        self.editingComplete()

    def findSuite(self, app):
        for suite in self.rootTestSuites:
            if suite.app is app:
                return suite

    def refreshFilesRecursively(self, suite):
        suite.filesChanged()
        if suite.classId() == "test-suite":
            for subTest in suite.testcases:
                self.refreshFilesRecursively(subTest)


class ViewTestFileInEditor(ViewInEditor):
    def _getTitle(self):
        return "View File"

    def isDefaultViewer(self, comparison):
        return not self.differencesActive(comparison) and \
               (not self.testRunning() or not guiplugins.guiConfig.getValue("follow_file_by_default"))

    def findExitHandlerInfo(self, fileName, *args):
        if self.dynamic:
            return self.editingComplete, ()

        # options file can change appearance of test (environment refs etc.)
        baseName = os.path.basename(fileName)
        if baseName.startswith("options"):
            tests = self.getTestsForFile("options", fileName)
            if len(tests) > 0:
                return self.handleOptionsEdit, (tests,)
        elif baseName.startswith("testsuite"):
            tests = self.getTestsForFile("testsuite", fileName)
            if len(tests) > 0:
                # refresh tests if this edited
                return self.handleTestSuiteEdit, (tests,)

        return self.editingComplete, ()

    def getTestsForFile(self, stem, fileName):
        tests = []
        for test in self.currTestSelection:
            defFile = test.getFileName(stem)
            if defFile and plugins.samefile(fileName, defFile):
                tests.append(test)
        return tests

    def handleTestSuiteEdit(self, suites):
        for suite in suites:
            suite.refresh(suite.app.getFilterList(suites))
        self.editingComplete()

    def handleOptionsEdit(self, tests):
        for test in tests:
            test.filesChanged()
        self.editingComplete()

class ViewFilteredTestFileInEditor(ViewTestFileInEditor):
    def _getStockId(self):
        pass # don't use same stock for both
    def useFiltered(self):
        return True
    def _getTitle(self):
        return "View Filtered File"
    def isActiveForFile(self, fileName, comparison):
        return bool(comparison)
    def isDefaultViewer(self, *args):
        return False

class ViewFilteredOrigFileInEditor(ViewFilteredTestFileInEditor):
    def _getTitle(self):
        return "View Filtered Original File"
    def getFileToView(self, fileName, associatedObject):
        try:
            # associatedObject might be a comparison object, but it might not
            # Use the comparison if it's there
            return associatedObject.getStdFile(self.useFiltered())
        except AttributeError:
            return fileName

class ViewOrigFileInEditor(ViewFilteredOrigFileInEditor):
    def _getTitle(self):
        return "View Original File"
    def useFiltered(self):
        return False


class ViewFileDifferences(FileViewAction):
    def _getTitle(self):
        return "View Raw Differences"

    def getToolConfigEntry(self):
        return "diff_program"

    def getToolDescription(self):
        return "graphical difference program"

    def isActiveForFile(self, fileName, comparison):
        if bool(comparison):
            if not (comparison.newResult() or comparison.missingResult()):
                return True
        return False

    def _performOnFile(self, diffProgram, tmpFile, comparison):
        stdFile = comparison.getStdFile(self.useFiltered())
        description = diffProgram + " " + os.path.basename(stdFile) + " " + os.path.basename(tmpFile)
        guiplugins.guilog.info("Starting graphical difference comparison using '" + diffProgram + "':")
        guiplugins.guilog.info("-- original file : " + stdFile)
        guiplugins.guilog.info("--  current file : " + tmpFile)
        cmdArgs = plugins.splitcmd(diffProgram) + [ stdFile, tmpFile ]
        self.startViewer(cmdArgs, description=description, exitHandler=self.diffingComplete)

    def diffingComplete(self, *args):
        guiplugins.scriptEngine.applicationEvent("the graphical diff program to terminate")


class ViewFilteredFileDifferences(ViewFileDifferences):
    def _getTitle(self):
        return "View Differences"

    def useFiltered(self):
        return True

    def isActiveForFile(self, fileName, comparison):
        return self.differencesActive(comparison)

    def isDefaultViewer(self, comparison):
        return self.differencesActive(comparison)


class FollowFile(FileViewAction):
    def _getTitle(self):
        return "Follow File Progress"

    def getToolConfigEntry(self):
        return "follow_program"

    def getToolDescription(self):
        return "file-following program"

    def isActiveForFile(self, *args):
        return self.testRunning()

    def fileToFollow(self, fileName, comparison):
        if comparison:
            return comparison.tmpFile
        else:
            return fileName

    def isDefaultViewer(self, comparison):
        return not self.differencesActive(comparison) and self.testRunning() and \
               guiplugins.guiConfig.getValue("follow_file_by_default")

    def getFollowProgram(self, followProgram, fileName):
        title = '"' + self.currTestSelection[0].name + " (" + os.path.basename(fileName) + ')"'
        envDir = { "TEXTTEST_FOLLOW_FILE_TITLE" : title } # Title of the window when following file progress
        return Template(followProgram).safe_substitute(envDir)

    def getFollowCommand(self, program, fileName):
        remoteHost = self.getRemoteHost()
        if remoteHost:
            remoteShellProgram = guiplugins.guiConfig.getValue("remote_shell_program")
            return [ remoteShellProgram, remoteHost, "env DISPLAY=" + self.getFullDisplay() + " " + \
                     program + " " + fileName ]
        else:
            return plugins.splitcmd(program) + [ fileName ]

    def _performOnFile(self, followProgram, fileName, comparison):
        useFile = self.fileToFollow(fileName, comparison)
        useProgram = self.getFollowProgram(followProgram, fileName)
        guiplugins.guilog.info("Following file " + useFile + " using '" + useProgram + "'")
        description = useProgram + " " + os.path.basename(useFile)
        cmdArgs = self.getFollowCommand(useProgram, useFile)
        self.startViewer(cmdArgs, description=description, exitHandler=self.followComplete)

    def followComplete(self, *args):
        guiplugins.scriptEngine.applicationEvent("the file-following program to terminate")


class KillTests(guiplugins.ActionGUI):
    def _getStockId(self):
        return "stop"
    def _getTitle(self):
        return "_Kill"
    def getTooltip(self):
        return "Kill selected tests"
    def isActiveOnCurrent(self, test=None, state=None):
        for seltest in self.currTestSelection:
            if seltest is test:
                if not state.isComplete():
                    return True
            else:
                if not seltest.state.isComplete():
                    return True
        return False
    def getSignalsSent(self):
        return [ "Kill" ]
    def performOnCurrent(self):
        tests = filter(lambda test: not test.state.isComplete(), self.currTestSelection)
        tests.reverse() # best to cut across the action thread rather than follow it and disturb it excessively
        testDesc = str(len(tests)) + " tests"
        self.notify("Status", "Killing " + testDesc + " ...")
        for test in tests:
            self.notify("ActionProgress", "")
            guiplugins.guilog.info("Killing " + repr(test))
            test.notify("Kill")

        self.notify("Status", "Killed " + testDesc + ".")

class ClipboardAction(guiplugins.ActionGUI):
    def isActiveOnCurrent(self, *args):
        if guiplugins.ActionGUI.isActiveOnCurrent(self, *args):
            for test in self.currTestSelection:
                if test.parent:
                    return True
        return False

    def getSignalsSent(self):
        return [ "Clipboard" ]

    def _getStockId(self):
        return self.getName()

    def _getTitle(self):
        return "_" + self.getName().capitalize()

    def getTooltip(self):
        return self.getName().capitalize() + " selected tests"

    def noAncestorsSelected(self, test):
        if not test.parent:
            return True
        if test.parent in self.currTestSelection:
            return False
        else:
            return self.noAncestorsSelected(test.parent)
        
    def performOnCurrent(self):
        # If suites are selected, don't also select their contents
        testsForClipboard = filter(self.noAncestorsSelected, self.currTestSelection)
        self.notify("Clipboard", testsForClipboard, cut=self.shouldCut())


class CopyTests(ClipboardAction):
    def getName(self):
        return "copy"
    def shouldCut(self):
        return False

class CutTests(ClipboardAction):
    def getName(self):
        return "cut"
    def shouldCut(self):
        return True

class PasteTests(guiplugins.ActionGUI):
    def __init__(self, *args):
        guiplugins.ActionGUI.__init__(self, *args)
        self.clipboardTests = []
        self.removeAfter = False
    def singleTestOnly(self):
        return True
    def _getStockId(self):
        return "paste"
    def _getTitle(self):
        return "_Paste"
    def getTooltip(self):
        return "Paste tests from clipboard"
    def notifyClipboard(self, tests, cut=False):
        self.clipboardTests = tests
        self.removeAfter = cut
        self.setSensitivity(True)

    def isActiveOnCurrent(self, test=None, state=None):
        return guiplugins.ActionGUI.isActiveOnCurrent(self, test, state) and len(self.clipboardTests) > 0
    def getCurrentTestMatchingApp(self, test):
        for currTest in self.currTestSelection:
            if currTest.app == test.app:
                return currTest

    def getDestinationInfo(self, test):
        currTest = self.getCurrentTestMatchingApp(test)
        if currTest is None:
            return None, 0
        if currTest.classId() == "test-suite" and currTest not in self.clipboardTests:
            return currTest, 0
        else:
            return currTest.parent, currTest.positionInParent() + 1

    def getNewTestName(self, suite, oldName):
        existingTest = suite.findSubtest(oldName)
        if not existingTest or self.willBeRemoved(existingTest):
            return oldName

        nextNameCandidate = self.findNextNameCandidate(oldName)
        return self.getNewTestName(suite, nextNameCandidate)
    def willBeRemoved(self, test):
        return self.removeAfter and test in self.clipboardTests
    def findNextNameCandidate(self, name):
        copyPos = name.find("_copy_")
        if copyPos != -1:
            copyEndPos = copyPos + 6
            number = int(name[copyEndPos:])
            return name[:copyEndPos] + str(number + 1)
        elif name.endswith("copy"):
            return name + "_2"
        else:
            return name + "_copy"
    def getNewDescription(self, test):
        if len(test.description) or self.removeAfter:
            return plugins.extractComment(test.description)
        else:
            return "Copy of " + test.name
    def getRepositionPlacement(self, test, placement):
        currPos = test.positionInParent()
        if placement > currPos:
            return placement - 1
        else:
            return placement

    def messageAfterPerform(self):
        pass # do it below...
        
    def performOnCurrent(self):
        newTests = []
        destInfo = seqdict()
        for test in self.clipboardTests:
            suite, placement = self.getDestinationInfo(test)
            if suite:
                destInfo[test] = suite, placement
        if len(destInfo) == 0:
            raise plugins.TextTestError, "Cannot paste test there, as the copied test and currently selected test have no application/version in common"

        suiteDeltas = {} # When we insert as we go along, need to update subsequent placements
        for test in self.clipboardTests:
            if not destInfo.has_key(test):
                continue
            suite, placement = destInfo[test]
            realPlacement = placement + suiteDeltas.get(suite, 0)
            newName = self.getNewTestName(suite, test.name)
            guiplugins.guilog.info("Pasting test " + newName + " under test suite " + \
                        repr(suite) + ", in position " + str(realPlacement))
            if self.removeAfter and newName == test.name and suite is test.parent:
                # Cut + paste to the same suite is basically a reposition, do it as one action
                repositionPlacement = self.getRepositionPlacement(test, realPlacement)
                plugins.tryFileChange(test.parent.repositionTest, "Failed to reposition test: no permissions to edit the testsuite file",
                                      test, repositionPlacement)
                newTests.append(test)
                suiteDeltas.setdefault(suite, 0)
            else:
                newDesc = self.getNewDescription(test)
                # Create test files first, so that if it fails due to e.g. full disk, we won't register the test either...
                testDir = suite.getNewDirectoryName(newName)
                self.moveOrCopy(test, testDir)
                suite.registerTest(newName, newDesc, realPlacement)
                testImported = suite.addTest(test.__class__, os.path.basename(testDir), newDesc, realPlacement)
                # "testImported" might in fact be a suite: in which case we should read all the new subtests which
                # might have also been copied
                testImported.readContents(initial=False)
                testImported.updateAllRelPaths(test.getRelPath())
                if suiteDeltas.has_key(suite):
                    suiteDeltas[suite] += 1
                else:
                    suiteDeltas[suite] = 1
                newTests.append(testImported)
                if self.removeAfter:
                    plugins.tryFileChange(test.remove, "Failed to remove old test: didn't have sufficient write permission to the test files. Test copied instead of moved.")
                    
        guiplugins.guilog.info("Selecting new tests : " + repr(newTests))
        self.notify("SetTestSelection", newTests)
        self.currTestSelection = newTests
        self.notify("Status", self.getStatusMessage(suiteDeltas))
        if self.removeAfter:
            # After a paste from cut, subsequent pastes should behave like copies of the new tests
            self.clipboardTests = newTests
            self.removeAfter = False
        for suite, placement in destInfo.values():
            suite.contentChanged()

    def getStatusMessage(self, suiteDeltas):
        suiteName = suiteDeltas.keys()[0].name
        if self.removeAfter:
            return "Moved " + self.describeTests() + " to suite '" + suiteName + "'"
        else:
            return "Pasted " +  self.describeTests() + " to suite '" + suiteName + "'"

    def getSignalsSent(self):
        return [ "SetTestSelection" ]

    def moveOrCopy(self, test, newDirName):
        # If it exists it's because a previous copy has already taken across the directory
        if not os.path.isdir(newDirName):
            oldDirName = test.getDirectory()
            if self.removeAfter:
                self.moveDirectory(oldDirName, newDirName)
            else:
                self.copyDirectory(oldDirName, newDirName)

    # Methods overridden by version control
    @staticmethod
    def moveDirectory(oldDirName, newDirName):
        os.rename(oldDirName, newDirName)

    @staticmethod
    def copyDirectory(oldDirName, newDirName):
        shutil.copytree(oldDirName, newDirName)
    


# And a generic import test. Note acts on test suites
class ImportTest(guiplugins.ActionDialogGUI):
    def __init__(self, *args):
        guiplugins.ActionDialogGUI.__init__(self, *args)
        self.optionGroup.addOption("name", self.getNameTitle())
        self.optionGroup.addOption("desc", self.getDescTitle(), description="Enter a description of the new " + self.testType().lower() + " which will be inserted as a comment in the testsuite file.")
        self.optionGroup.addOption("testpos", self.getPlaceTitle(), "last in suite", allocateNofValues=2, description="Where in the test suite should the test be placed?")
        self.testImported = None
    def getConfirmationMessage(self):
        testName = self.getNewTestName()
        suite = self.getDestinationSuite()
        self.checkName(suite, testName)
        newDir = os.path.join(suite.getDirectory(), testName)
        if os.path.isdir(newDir):
            if self.testFilesExist(newDir, suite.app):
                raise plugins.TextTestError, "Test already exists for application " + suite.app.fullName + \
                          " : " + os.path.basename(newDir)
            else:
                return "Test directory already exists for '" + testName + "'\nAre you sure you want to use this name?"
        else:
            return ""
    def _getStockId(self):
        return "add"
    def getResizeDivisors(self):
        # size of the dialog
        return 1.5, 2.8

    def testFilesExist(self, dir, app):
        for fileName in os.listdir(dir):
            parts = fileName.split(".")
            if len(parts) > 1 and parts[1] == app.name:
                return True
        return False
    def singleTestOnly(self):
        return True
    def correctTestClass(self):
        return "test-suite"
    def getNameTitle(self):
        return self.testType() + " Name"
    def getDescTitle(self):
        return self.testType() + " Description"
    def getPlaceTitle(self):
        return "\nPlace " + self.testType()
    def updateOptions(self):
        self.optionGroup.setOptionValue("name", self.getDefaultName())
        self.optionGroup.setOptionValue("desc", self.getDefaultDesc())
        self.setPlacements(self.currTestSelection[0])
        return True

    def setPlacements(self, suite):
        # Add suite and its children
        placements = [ "first in suite" ]
        for test in suite.testcases:
            placements += [ "after " + test.name ]
        placements.append("last in suite")

        self.optionGroup.setPossibleValues("testpos", placements)
        self.optionGroup.getOption("testpos").reset()
    def getDefaultName(self):
        return ""
    def getDefaultDesc(self):
        return ""
    def _getTitle(self):
        return "Add " + self.testType()
    def testType(self): #pragma : no cover - doc only
        return ""
    def messageAfterPerform(self):
        if self.testImported:
            return "Added new " + repr(self.testImported)
    def getNewTestName(self):
        # Overwritten in subclasses - occasionally it can be inferred
        return self.optionGroup.getOptionValue("name").strip()
    def performOnCurrent(self):
        testName = self.getNewTestName()
        suite = self.getDestinationSuite()

        guiplugins.guilog.info("Adding " + self.testType() + " " + testName + " under test suite " + \
                    repr(suite) + ", placed " + self.optionGroup.getOptionValue("testpos"))
        placement = self.getPlacement()
        description = self.optionGroup.getOptionValue("desc")
        suite.registerTest(testName, description, placement)
        testDir = suite.makeSubDirectory(testName)
        self.testImported = self.createTestContents(suite, testDir, description, placement)
        suite.contentChanged()
        guiplugins.guilog.info("Selecting new test " + self.testImported.name)
        self.notify("SetTestSelection", [ self.testImported ])
    def getSignalsSent(self):
        return [ "SetTestSelection" ]
    def getDestinationSuite(self):
        return self.currTestSelection[0]
    def getPlacement(self):
        option = self.optionGroup.getOption("testpos")
        return option.possibleValues.index(option.getValue())
    def checkName(self, suite, testName):
        if len(testName) == 0:
            raise plugins.TextTestError, "No name given for new " + self.testType() + "!" + "\n" + \
                  "Fill in the 'Adding " + self.testType() + "' tab below."
        if testName.find(" ") != -1:
            raise plugins.TextTestError, "The new " + self.testType() + \
                  " name is not permitted to contain spaces, please specify another"
        for test in suite.testcases:
            if test.name == testName:
                raise plugins.TextTestError, "A " + self.testType() + " with the name '" + \
                      testName + "' already exists, please choose another name"


class ImportTestCase(ImportTest):
    def __init__(self, *args):
        ImportTest.__init__(self, *args)
        self.addDefinitionFileOption()
    def testType(self):
        return "Test"
    def addDefinitionFileOption(self):
        self.addOption("opt", "Command line options")
    def createTestContents(self, suite, testDir, description, placement):
        self.writeDefinitionFiles(suite, testDir)
        self.writeEnvironmentFile(suite, testDir)
        self.writeResultsFiles(suite, testDir)
        return suite.addTestCase(os.path.basename(testDir), description, placement)
    def getWriteFileName(self, name, suite, testDir):
        return os.path.join(testDir, name + "." + suite.app.name)
    def getWriteFile(self, name, suite, testDir):
        return open(self.getWriteFileName(name, suite, testDir), "w")
    def writeEnvironmentFile(self, suite, testDir):
        envDir = self.getEnvironment(suite)
        if len(envDir) == 0:
            return
        envFile = self.getWriteFile("environment", suite, testDir)
        for var, value in envDir.items():
            guiplugins.guilog.info("Setting test env: " + var + " = " + value)
            envFile.write(var + ":" + value + "\n")
        envFile.close()
    def writeDefinitionFiles(self, suite, testDir):
        optionString = self.getOptions(suite)
        if len(optionString):
            guiplugins.guilog.info("Using option string : " + optionString)
            optionFile = self.getWriteFile("options", suite, testDir)
            optionFile.write(optionString + "\n")
        else:
            guiplugins.guilog.info("Not creating options file")
        return optionString
    def getOptions(self, suite):
        return self.optionGroup.getOptionValue("opt")
    def getEnvironment(self, suite):
        return {}
    def writeResultsFiles(self, suite, testDir):
        # Cannot do anything in general
        pass

class ImportTestSuite(ImportTest):
    def __init__(self, *args):
        ImportTest.__init__(self, *args)
        self.addEnvironmentFileOptions()
    def testType(self):
        return "Suite"
    def createTestContents(self, suite, testDir, description, placement):
        return suite.addTestSuite(os.path.basename(testDir), description, placement, self.writeEnvironmentFiles)
    def addEnvironmentFileOptions(self):
        self.addSwitch("env", "Add environment file")
    def writeEnvironmentFiles(self, newSuite):
        if self.optionGroup.getSwitchValue("env"):
            envFile = os.path.join(newSuite.getDirectory(), "environment")
            file = open(envFile, "w")
            file.write("# Dictionary of environment to variables to set in test suite\n")


class ImportApplication(guiplugins.ActionDialogGUI):
    def __init__(self, allApps, *args):
        guiplugins.ActionDialogGUI.__init__(self, allApps, *args)
        self.textTestHome = os.getenv("TEXTTEST_HOME")
        self.addOption("name", "Full name of application", description="Name of application to use in reports etc.")
        self.addOption("ext", "\nFile extension to use for TextTest files associated with this application", description="Short space-free extension, to identify all TextTest's files associated with this application")
        self.addOption("subdir", "\nSubdirectory of TEXTTEST_HOME to store the above application files under (leave blank for local storage)", possibleValues=self.findSubDirectories())
        possibleDirs = []
        for app in allApps:
            if app.getDirectory() not in possibleDirs:
                possibleDirs.append(app.getDirectory())
        if len(possibleDirs) == 0:
            possibleDirs = [ self.textTestHome ]
        self.addOption("exec", "\nSelect executable program to test", description="The full path to the program you want to test", possibleDirs=possibleDirs, selectFile=True)

    def findSubDirectories(self):
        usableFiles = filter(lambda f: f not in plugins.controlDirNames, os.listdir(self.textTestHome))
        allFiles = [ os.path.join(self.textTestHome, f) for f in usableFiles ]
        allDirs = filter(os.path.isdir, allFiles)
        allDirs.sort()
        return map(os.path.basename, allDirs)

    def notifyAllRead(self):
        if self.noApps:
            self.runInteractive()

    def isActiveOnCurrent(self, *args):
        return True
    def _getStockId(self):
        return "add"
    def _getTitle(self):
        return "Add Application"
    def messageAfterPerform(self):
        pass
    def getTooltip(self):
        return "Define a new tested application"

    def checkSanity(self, ext, executable, directory):
        if not ext:
            raise plugins.TextTestError, "Must provide a file extension for TextTest files"

        if not executable or not os.path.isfile(executable):
            raise plugins.TextTestError, "Must provide a valid path to a program to test"

        if os.path.exists(os.path.join(directory, "config." + ext)):
            raise plugins.TextTestError, "Test-application already exists at the indicated location with the indicated extension: please choose another name"

    def getSignalsSent(self):
        return [ "NewApplication" ]

    def performOnCurrent(self):
        executable = self.optionGroup.getOptionValue("exec")
        ext = self.optionGroup.getOptionValue("ext")
        directory = os.path.normpath(os.path.join(self.textTestHome, self.optionGroup.getOptionValue("subdir")))
        self.checkSanity(ext, executable, directory)
        plugins.ensureDirectoryExists(directory)
        configEntries = { "executable" : executable }
        fullName = self.optionGroup.getOptionValue("name")
        if fullName:
            configEntries["full_name"] = fullName
        self.notify("NewApplication", ext, directory, configEntries)
        self.notify("Status", "Created new application with extension '" + ext + "'.")


class AllTestsHandler:
    def __init__(self):
        self.rootTestSuites = []
    def addSuites(self, suites):
        self.rootTestSuites += suites
    def findAllTests(self):
        return reduce(operator.add, (suite.testCaseList() for suite in self.rootTestSuites), [])
    def findTestsNotIn(self, tests):
        return filter(lambda test: test not in tests, self.findAllTests())


class SelectTests(guiplugins.ActionTabGUI, AllTestsHandler):
    def __init__(self, allApps, *args):
        guiplugins.ActionTabGUI.__init__(self, allApps)
        AllTestsHandler.__init__(self)
        self.filterAction = gtk.Action("Filter", "Filter", \
                                       self.getFilterTooltip(), self.getStockId())
        guiplugins.scriptEngine.connect(self.getFilterTooltip(), "activate", self.filterAction, self.filterTests)
        self.selectDiag = logging.getLogger("Select Tests")
        self.addOption("vs", "Tests for version", description="Select tests for a specific version.",
                       possibleValues=self.getPossibleVersions(allApps))
        self.selectionGroup = plugins.OptionGroup(self.getTabTitle())
        self.selectionGroup.addSwitch("select_in_collapsed_suites", "Select in collapsed suites", 0, description="Select in currently collapsed suites as well?")
        currSelectDesc = ["Unselect all currently selected tests before applying the new selection criteria.",
                          "Apply the new selection criteria only to the currently selected tests, to obtain a subselection.",
                          "Keep the currently selected tests even if they do not match the new criteria, and extend the selection with all other tests which meet the new criteria.",
                          "After applying the new selection criteria to all tests, unselect the currently selected tests, to exclude them from the new selection." ]
        self.selectionGroup.addSwitch("current_selection", options = [ "Discard", "Refine", "Extend", "Exclude"],
                                      description=currSelectDesc)
        self.filteringGroup = plugins.OptionGroup(self.getTabTitle())
        currFilterDesc = ["Show all tests which match the criteria, and hide all those that do not.",
                          "Hide all tests which do not match the criteria. Do not show any tests that aren't already shown.",
                          "Show all tests which match the criteria. Do not hide any tests that are currently shown." ]
        self.filteringGroup.addSwitch("current_filtering", options = [ "Discard", "Refine", "Extend" ], description=currFilterDesc)
        excludeKeys = set(self.optionGroup.keys()) # remember these so we don't try and save them to selections
        self.addApplicationOptions(allApps)
        self.appKeys = set(self.optionGroup.keys())
        self.appKeys.difference_update(excludeKeys)

    def addSuites(self, suites):
        guiplugins.ActionTabGUI.addSuites(self, suites)
        AllTestsHandler.addSuites(self, suites)

    def addToGroups(self, actionGroup, accelGroup):
        guiplugins.ActionTabGUI.addToGroups(self, actionGroup, accelGroup)
        self.filterAccel = self._addToGroups("Filter", self.filterAction, actionGroup, accelGroup)

    def notifyAllRead(self, *args):
        allStems = self.findAllStems()
        defaultTestFile = self.findDefaultTestFile(allStems)
        self.optionGroup.setValue("grepfile", defaultTestFile)
        self.optionGroup.setPossibleValues("grepfile", allStems)
        self.contentsChanged()

    def findDefaultTestFile(self, allStems):
        if len(allStems) == 0:
            return "output"
        for app in self.validApps:
            logFile = app.getConfigValue("log_file")
            if logFile in allStems:
                return logFile
        return allStems[0]

    def findAllStems(self):
        stems = {}
        for suite in self.rootTestSuites:
            exclude = suite.app.getDataFileNames() + [ "file_edits" ]
            for test in suite.testCaseList():
                for stem in test.dircache.findAllStems(exclude):
                    if stem in stems:
                        stems[stem] += 1
                    else:
                        stems[stem] = 1
        return sorted(stems.keys(), lambda x,y: cmp(stems.get(y), stems.get(x)))
    def getPossibleVersions(self, allApps):
        possVersions = []
        for app in allApps:
            for possVersion in self._getPossibleVersions(app):
                if possVersion not in possVersions:
                    possVersions.append(possVersion)
        return possVersions
    def _getPossibleVersions(self, app):
        fullVersion = app.getFullVersion()
        extraVersions = app.getExtraVersions()
        if len(fullVersion) == 0:
            return [ "<default>" ] + extraVersions
        else:
            return [ fullVersion ] + [ fullVersion + "." + extra for extra in extraVersions ]
    def isActiveOnCurrent(self, *args):
        return True
    def getSignalsSent(self):
        return [ "SetTestSelection", "Visibility" ]
    def _getStockId(self):
        return "find"
    def _getTitle(self):
        return "_Select"
    def getTooltip(self):
        return "Select indicated tests"
    def getTabTitle(self):
        return "Selection"
    def getGroupTabTitle(self):
        return "Selection"
    def messageBeforePerform(self):
        return "Selecting tests ..."
    def messageAfterPerform(self):
        return "Selected " + self.describeTests() + "."
    # No messageAfterPerform necessary - we update the status bar when the selection changes inside TextTestGUI
    def getFilterList(self, app):
        return app.getFilterList(self.rootTestSuites, self.optionGroup.getOptionValueMap())
    def makeNewSelection(self):
        # Get strategy. 0 = discard, 1 = refine, 2 = extend, 3 = exclude
        strategy = self.selectionGroup.getSwitchValue("current_selection")
        return self._makeNewSelection(strategy)
    def notifyReset(self):
        self.optionGroup.reset()
        self.selectionGroup.reset()
        self.filteringGroup.reset()
        self.contentsChanged()
    def _makeNewSelection(self, strategy=0):
        selectedTests = []
        suitesToTry = self.getSuitesToTry()
        for suite in self.rootTestSuites:
            if suite in suitesToTry:
                filters = self.getFilterList(suite.app)
                reqTests = self.getRequestedTests(suite, filters)
                newTests = self.combineWithPrevious(reqTests, suite.app, strategy)
            else:
                newTests = self.combineWithPrevious([], suite.app, strategy)

            guiplugins.guilog.info("Selected " + str(len(newTests)) + " out of a possible " + str(suite.size()))
            selectedTests += newTests
        return selectedTests

    def performOnCurrent(self):
        newSelection = self.makeNewSelection()
        criteria = " ".join(self.optionGroup.getCommandLines(onlyKeys=self.appKeys))
        self.notify("SetTestSelection", newSelection, criteria, self.selectionGroup.getSwitchValue("select_in_collapsed_suites"))

    def getSuitesToTry(self):
        # If only some of the suites present match the version selection, only consider them.
        # If none of them do, try to filter them all
        versionSelection = self.optionGroup.getOptionValue("vs")
        if len(versionSelection) == 0:
            return self.rootTestSuites
        versions = versionSelection.split(".")
        toTry = []
        for suite in self.rootTestSuites:
            if self.allVersionsMatch(versions, suite.app.versions):
                toTry.append(suite)
        if len(toTry) == 0:
            return self.rootTestSuites
        else:
            return toTry
    def allVersionsMatch(self, versions, appVersions):
        for version in versions:
            if version == "<default>":
                if len(appVersions) > 0:
                    return False
            else:
                if not version in appVersions:
                    return False
        return True
    def getRequestedTests(self, suite, filters):
        self.notify("ActionProgress", "") # Just to update gui ...
        if not suite.isAcceptedByAll(filters):
            return []
        if suite.classId() == "test-suite":
            tests = []
            for subSuite in self.findTestCaseList(suite):
                tests += self.getRequestedTests(subSuite, filters)
            return tests
        else:
            return [ suite ]
    def combineWithPrevious(self, reqTests, app, strategy):
        # Strategies: 0 - discard, 1 - refine, 2 - extend, 3 - exclude
        # If we want to extend selection, we include test if it was previsouly selected,
        # even if it doesn't fit the current criterion
        if strategy == 0:
            return reqTests
        elif strategy == 1:
            return filter(lambda test: test in self.currTestSelection, reqTests)
        else:
            extraRequested = filter(lambda test: test not in self.currTestSelection, reqTests)
            if strategy == 2:
                selectedThisApp = filter(lambda test: test.app is app, self.currTestSelection)
                return extraRequested + selectedThisApp
            elif strategy == 3:
                return extraRequested
    def findTestCaseList(self, suite):
        version = self.optionGroup.getOptionValue("vs")
        if len(version) == 0:
            return suite.testcases

        if version == "<default>":
            version = ""

        fullVersion = suite.app.getFullVersion()
        versionToUse = self.findCombinedVersion(version, fullVersion)
        self.selectDiag.info("Trying to get test cases for " + repr(suite) + ", version " + versionToUse)
        return suite.findTestCases(versionToUse)

    def findCombinedVersion(self, version, fullVersion):
        combined = version
        if len(fullVersion) > 0 and len(version) > 0:
            parts = version.split(".")
            for appVer in fullVersion.split("."):
                if not appVer in parts:
                    combined += "." + appVer
        return combined

    def filterTests(self, *args):
        self.notify("Status", "Filtering tests ...")
        self.notify("ActionStart")
        newSelection = self._makeNewSelection()
        strategy = self.filteringGroup.getSwitchValue("current_filtering")
        toShow = self.findTestsToShow(newSelection, strategy)
        self.notify("Visibility", toShow, True)
        self.notify("ActionProgress", "")
        toHide = self.findTestsToHide(newSelection, strategy)
        self.notify("Visibility", toHide, False)
        self.notify("ActionStop")
        self.notify("Status", "Changed filtering by showing " + str(len(toShow)) +
                    " tests and hiding " + str(len(toHide)) + ".")

    def findTestsToShow(self, newSelection, strategy):
        if strategy == 0 or strategy == 2:
            return newSelection
        else:
            return []

    def findTestsToHide(self, newSelection, strategy):
        if strategy == 0 or strategy == 1:
            return self.findTestsNotIn(newSelection)
        else:
            return []

    def getFilterTooltip(self):
        return "filter tests to show only those indicated"

    def createFilterButton(self):
        button = gtk.Button()
        self.filterAction.connect_proxy(button)
        button.set_image(gtk.image_new_from_stock(self.getStockId(), gtk.ICON_SIZE_BUTTON))
        self.tooltips.set_tip(button, self.getFilterTooltip())
        return button

    def createFrame(self, name, group, button):
        frame = gtk.Frame(name)
        frame.set_label_align(0.5, 0.5)
        frame.set_shadow_type(gtk.SHADOW_IN)
        frameBox = gtk.VBox()
        self.fillVBox(frameBox, group)
        self.addCentralButton(frameBox, button)
        frame.add(frameBox)
        return frame

    def getNewSwitchName(self, switchName, optionGroup):
        if len(switchName):
            return switchName
        elif optionGroup is self.selectionGroup:
            return "Current selection"
        elif optionGroup is self.filteringGroup:
            return "Current filtering"
        else:
            return switchName

    def getNaming(self, switchName, cleanOption, optionGroup):
        return guiplugins.ActionTabGUI.getNaming(self, self.getNewSwitchName(switchName, optionGroup), cleanOption, optionGroup)

    def createButtons(self, vbox):
        selFrame = self.createFrame("Selection", self.selectionGroup, self.createButton())
        vbox.pack_start(selFrame, fill=False, expand=False, padding=8)
        filterFrame = self.createFrame("Filtering", self.filteringGroup, self.createFilterButton())
        vbox.pack_start(filterFrame, fill=False, expand=False, padding=8)

    def describeAction(self):
        self._describeAction(self.gtkAction, self.accelerator)
        self._describeAction(self.filterAction, self.filterAccel)


class HideSelected(guiplugins.ActionGUI,AllTestsHandler):
    def __init__(self, *args):
        guiplugins.ActionGUI.__init__(self, *args)
        AllTestsHandler.__init__(self)
    def addSuites(self, suites):
        guiplugins.ActionGUI.addSuites(self, suites)
        AllTestsHandler.addSuites(self, suites)
    def _getTitle(self):
        return "Hide selected"
    def messageBeforePerform(self):
        return "Hiding all tests that are currently selected ..."
    def getTooltip(self):
        return "Hide all tests that are currently selected"
    def getSignalsSent(self):
        return [ "Visibility" ]
    def performOnCurrent(self):
        self.notify("Visibility", self.currTestSelection, False)


class HideUnselected(guiplugins.ActionGUI,AllTestsHandler):
    def __init__(self, *args):
        guiplugins.ActionGUI.__init__(self, *args)
        AllTestsHandler.__init__(self)
    def addSuites(self, suites):
        guiplugins.ActionGUI.addSuites(self, suites)
        AllTestsHandler.addSuites(self, suites)
    def _getTitle(self):
        return "Show only selected"
    def messageBeforePerform(self):
        return "Showing only tests that are currently selected ..."
    def getTooltip(self):
        return "Show only tests that are currently selected"
    def getSignalsSent(self):
        return [ "Visibility" ]
    def performOnCurrent(self):
        self.notify("Visibility", self.findTestsNotIn(self.currTestSelection), False)


class ShowAll(guiplugins.BasicActionGUI,AllTestsHandler):
    def __init__(self, *args):
        guiplugins.BasicActionGUI.__init__(self, *args)
        AllTestsHandler.__init__(self)
    def _getTitle(self):
        return "Show all"
    def messageBeforePerform(self):
        return "Showing all tests..."
    def getTooltip(self):
        return "Show all tests"
    def getSignalsSent(self):
        return [ "Visibility" ]
    def performOnCurrent(self):
        self.notify("Visibility", self.findAllTests(), True)


class ResetGroups(guiplugins.BasicActionGUI):
    def isActiveOnCurrent(self, *args):
        return True
    def _getStockId(self):
        return "revert-to-saved"
    def _getTitle(self):
        return "R_eset"
    def messageAfterPerform(self):
        return "All options reset to default values."
    def getTooltip(self):
        return "Reset running options"
    def getSignalsSent(self):
        return [ "Reset" ]
    def performOnCurrent(self):
        self.notify("Reset")

class AnnotateGUI(guiplugins.ActionDialogGUI):
    def __init__(self, *args):
        guiplugins.ActionDialogGUI.__init__(self, *args)
        self.addOption("desc", "\nDescription of this run")
    def isActiveOnCurrent(self, *args):
        return True
    def _getStockId(self):
        return "index"
    def _getTitle(self):
        return "Annotate"
    def messageAfterPerform(self):
        pass
    def getDialogTitle(self):
        return "Annotate this run"
    def getTooltip(self):
        return "Provide an annotation for this run and warn before closing it"
    def getSignalsSent(self):
        return [ "Annotate" ]
    def performOnCurrent(self):
        description = self.optionGroup.getOptionValue("desc")
        self.notify("Annotate", description)
        self.notify("Status", "Annotated GUI as '" + description + "'")

class SaveSelection(guiplugins.ActionDialogGUI):
    def __init__(self, allApps, dynamic):
        guiplugins.ActionDialogGUI.__init__(self, allApps, dynamic)
        self.addOption("f", "enter filter-file name =", possibleDirs=self.getFilterFileDirs(allApps), saveFile=True)
        if not dynamic:
            # In the static GUI case, we also want radiobuttons specifying
            # whether we want to save the actual tests, or the selection criteria.
            self.addSwitch("tests", "Save", options= [ "_List of selected tests", "C_riteria entered in the Selection tab\n(Might not match current selection, if it has been modified)" ])
        self.selectionCriteria = ""
        self.dynamic = dynamic
        self.rootTestSuites = []
    def addSuites(self, suites):
        guiplugins.ActionDialogGUI.addSuites(self, suites)
        self.rootTestSuites += suites
    def _getStockId(self):
        return "save-as"
    def _getTitle(self):
        return "S_ave Selection..."
    def getTooltip(self):
        return "Save selected tests in file"
        return self.folders
    def getTestPathFilterArg(self):
        selTestPaths = []
        testCaseSelection = self.getTestCaseSelection()
        for suite in self.rootTestSuites:
            selTestPaths.append("appdata=" + suite.app.name + suite.app.versionSuffix())
            for test in suite.testCaseList():
                if test in testCaseSelection:
                    selTestPaths.append(test.getRelPath())
        return "-tp " + "\n".join(selTestPaths)
    def notifySetTestSelection(self, tests, criteria="", *args):
        self.selectionCriteria = criteria
    def getTextToSave(self):
        if self.dynamic or not self.optionGroup.getSwitchValue("tests"):
            return self.getTestPathFilterArg()
        else:
            return self.selectionCriteria
    def getConfirmationMessage(self):
        fileName = self.optionGroup.getOptionValue("f")
        if fileName and os.path.isfile(fileName):
            return "\nThe file \n" + fileName + "\nalready exists.\n\nDo you want to overwrite it?\n"

    def getConfirmationDialogSettings(self):
        return gtk.STOCK_DIALOG_QUESTION, "Query"

    def notifySaveSelection(self, fileName):
        toSave = self.getTestPathFilterArg()
        self.writeFile(fileName, toSave)
    def performOnCurrent(self):
        toWrite = self.getTextToSave()
        fileName = self.optionGroup.getOptionValue("f")
        if not fileName:
            raise plugins.TextTestError, "Cannot save selection - no file name specified"
        elif os.path.isdir(fileName):
            raise plugins.TextTestError, "Cannot save selection - existing directory specified"
        else:
            self.writeFile(fileName, toWrite)
    def writeFile(self, fileName, toWrite):
        try:
            file = open(fileName, "w")
            file.write(toWrite + "\n")
            file.close()
        except IOError, e:
            raise plugins.TextTestError, "\nFailed to save selection:\n" + str(e) + "\n"
    def messageAfterPerform(self):
        return "Saved " + self.describeTests() + " in file '" + self.optionGroup.getOptionValue("f") + "'."


class LoadSelection(guiplugins.ActionDialogGUI):
    def __init__(self, allApps, *args):
        guiplugins.ActionDialogGUI.__init__(self, allApps, *args)
        self.addOption("f", "select filter-file", possibleDirs=self.getFilterFileDirs(allApps), selectFile=True)
        self.rootTestSuites = []

    def addSuites(self, suites):
        guiplugins.ActionDialogGUI.addSuites(self, suites)
        self.rootTestSuites += suites
    def isActiveOnCurrent(self, *args):
        return True
    def getSignalsSent(self):
        return [ "SetTestSelection" ]
    def _getStockId(self):
        return "open"
    def _getTitle(self):
        return "_Load Selection..."
    def getTooltip(self):
        return "Load test selection from file"
    def performOnCurrent(self):
        fileName = self.optionGroup.getOptionValue("f")
        if fileName:
            newSelection = self.makeNewSelection(fileName)
            guiplugins.guilog.info("Loaded " + str(len(newSelection)) + " tests from " + fileName)
            self.notify("SetTestSelection", newSelection, "-f " + fileName, True)
            self.notify("Status", "Loaded test selection from file '" + fileName + "'.")
        else:
            self.notify("Status", "No test selection loaded.")

    def makeNewSelection(self, fileName):
        tests = []
        for suite in self.rootTestSuites:
            filters = suite.app.getFiltersFromFile(fileName, self.rootTestSuites)
            tests += suite.testCaseList(filters)
        return tests
    def getResizeDivisors(self):
        # size of the dialog
        return 1.2, 1.7

    def messageBeforePerform(self):
        return "Loading test selection ..."
    def messageAfterPerform(self):
        pass

class RunningAction:
    runNumber = 1
    def getGroupTabTitle(self):
        return "Running"
    def messageAfterPerform(self):
        return self.performedDescription() + " " + self.describeTests() + " at " + plugins.localtime() + "."

    def performOnCurrent(self):
        self.startTextTestProcess(self.getUseCaseName(), [ "-g" ])
    def startTextTestProcess(self, usecase, runModeOptions):
        app = self.currAppSelection[0]
        writeDir = os.path.join(app.writeDirectory, "dynamic_run" + str(self.runNumber))
        plugins.ensureDirectoryExists(writeDir)
        filterFile = self.writeFilterFile(writeDir)
        ttOptions = runModeOptions + self.getTextTestOptions(filterFile, app, usecase)
        guiplugins.guilog.info("Starting " + usecase + " run of TextTest with arguments " + repr(ttOptions))
        logFile = os.path.join(writeDir, "output.log")
        errFile = os.path.join(writeDir, "errors.log")
        RunningAction.runNumber += 1
        description = "Dynamic GUI started at " + plugins.localtime()
        cmdArgs = self.getTextTestArgs() + ttOptions
        env = self.getNewUseCaseEnvironment(usecase)
        guiplugins.processMonitor.startProcess(cmdArgs, description, env=env,
                                               stdout=open(logFile, "w"), stderr=open(errFile, "w"),
                                               exitHandler=self.checkTestRun,
                                               exitHandlerArgs=(errFile,self.currTestSelection,usecase))

    def getNewUseCaseEnvironment(self, usecase):
        environ = deepcopy(os.environ)
        recScript = os.getenv("USECASE_RECORD_SCRIPT")
        if recScript:
            environ["USECASE_RECORD_SCRIPT"] = plugins.addLocalPrefix(recScript, usecase)
        repScript = os.getenv("USECASE_REPLAY_SCRIPT")
        if repScript:
            # Dynamic GUI might not record anything (it might fail) - don't try to replay files that
            # aren't there...
            dynRepScript = plugins.addLocalPrefix(repScript, usecase)
            if os.path.isfile(dynRepScript):
                environ["USECASE_REPLAY_SCRIPT"] = dynRepScript
            else:
                del environ["USECASE_REPLAY_SCRIPT"]
        return environ
    def getSignalsSent(self):
        return [ "SaveSelection" ]
    def writeFilterFile(self, writeDir):
        # Because the description of the selection can be extremely long, we write it in a file and refer to it
        # This avoids too-long command lines which are a problem at least on Windows XP
        filterFileName = os.path.join(writeDir, "gui_select")
        self.notify("SaveSelection", filterFileName)
        return filterFileName
    def getTextTestArgs(self):
        extraArgs = plugins.splitcmd(os.getenv("TEXTTEST_DYNAMIC_GUI_PYARGS", "")) # Additional python arguments for dynamic GUI : mostly useful for coverage
        return [ sys.executable ] + extraArgs + [ sys.argv[0] ]
    def getOptionGroups(self):
        return [ self.optionGroup ]
    def getTextTestOptions(self, filterFile, app, usecase):
        ttOptions = self.getCmdlineOptionForApps()
        for group in self.getOptionGroups():
            ttOptions += group.getCommandLines(self.getCommandLineKeys(usecase))
        # May be slow to calculate for large test suites, cache it
        self.testCount = len(self.getTestCaseSelection())
        ttOptions += [ "-count", str(self.testCount * self.getCountMultiplier()) ]
        ttOptions += [ "-f", filterFile ]
        ttOptions += [ "-fd", self.getTmpFilterDir(app) ]
        return ttOptions
    def getCommandLineKeys(self, usecase):
        # assume everything by default
        return []
    def getCountMultiplier(self):
        return 1
    
    def getTmpFilterDir(self, app):
        return os.path.join(app.writeDirectory, "temporary_filter_files")
    def getCmdlineOptionForApps(self):
        appNames = set([ app.name for app in self.currAppSelection ])
        return [ "-a", ",".join(sorted(list(appNames))) ]
    def checkTestRun(self, errFile, testSel, usecase):
        if self.checkErrorFile(errFile, testSel, usecase):
            self.handleCompletion(testSel, usecase)
            if len(self.currTestSelection) >= 1 and self.currTestSelection[0] in testSel:
                self.currTestSelection[0].filesChanged()

        testSel[0].notify("CloseDynamic", usecase)

    def readAndFilter(self, errFile, testSel):
        errText = ""
        triggerGroup = plugins.TextTriggerGroup(testSel[0].getConfigValue("suppress_stderr_popup"))
        for line in open(errFile).xreadlines():
            if not triggerGroup.stringContainsText(line):
                errText += line
        return errText
    def checkErrorFile(self, errFile, testSel, usecase):
        if os.path.isfile(errFile):
            errText = self.readAndFilter(errFile, testSel)
            if len(errText):
                self.notify("Status", usecase.capitalize() + " run failed for " + repr(testSel[0]))
                self.showErrorDialog(usecase.capitalize() + " run failed, with the following errors:\n" + errText)
                return False
        return True

    def handleCompletion(self, *args):
        pass # only used when recording

    def getConfirmationMessage(self):
        # For extra speed we check the selection first before we calculate all the test cases again...
        if len(self.currTestSelection) > 1 or len(self.getTestCaseSelection()) > 1:
            multiTestWarning = self.getMultipleTestWarning()
            if multiTestWarning:
                return "You are trying to " + multiTestWarning + ".\nThis will mean lots of target application GUIs " + \
                       "popping up and may be hard to follow.\nAre you sure you want to do this?"
        return ""

    def getMultipleTestWarning(self):
        pass


class ReconnectToTests(RunningAction,guiplugins.ActionDialogGUI):
    def __init__(self, *args):
        guiplugins.ActionDialogGUI.__init__(self, *args)
        self.addOption("v", "Version to reconnect to")
        self.addOption("reconnect", "Temporary result directory", os.getenv("TEXTTEST_TMP", ""), selectDir=True, description="Specify a directory containing temporary texttest results. The reconnection will use a random subdirectory matching the version used.")
        self.addSwitch("reconnfull", "Recomputation", 0, ["Display results exactly as they were in the original run", "Use raw data from the original run, but recompute run-dependent text, known bug information etc."])
    def _getStockId(self):
        return "connect"
    def _getTitle(self):
        return "Re_connect"
    def getTooltip(self):
        return "Reconnect to previously run tests"
    def getTabTitle(self):
        return "Reconnect"
    def performedDescription(self):
        return "Reconnected to"
    def getUseCaseName(self):
        return "reconnect"

class RunTests(RunningAction,guiplugins.ActionTabGUI):
    optionGroups = []
    def __init__(self, allApps, *args):
        guiplugins.ActionTabGUI.__init__(self, allApps)
        self.optionGroups.append(self.optionGroup)
        self.addApplicationOptions(allApps)

    def _getTitle(self):
        return "_Run"
    def _getStockId(self):
        return "execute"
    def getTooltip(self):
        return "Run selected tests"
    def getOptionGroups(self):
        return self.optionGroups
    def getCountMultiplier(self):
        return self.getCopyCount() * self.getVersionCount()
    def getCopyCount(self):
        return int(self.optionGroups[0].getOptionValue("cp"))
    def getVersionCount(self):
        return self.optionGroups[0].getOptionValue("v").count(",") + 1
    def performedDescription(self):
        timesToRun = self.getCopyCount()
        numberOfTests = self.testCount
        if timesToRun != 1:
            if numberOfTests > 1:
                return "Started " + str(timesToRun) + " copies each of"
            else:
                return "Started " + str(timesToRun) + " copies of"
        else:
            return "Started"
    def getUseCaseName(self):
        return "dynamic"
    def getMultipleTestWarning(self):
        app = self.currTestSelection[0].app
        for group in self.optionGroups:
            for switchName, desc in app.getInteractiveReplayOptions():
                if group.getSwitchValue(switchName, False):
                    return "run " + self.describeTests() + " with " + desc + " replay enabled"

class RunTestsBasic(RunTests):
    def getTabTitle(self):
        return "Basic"

class RunTestsAdvanced(RunTests):
    def getTabTitle(self):
        return "Advanced"

class RecordTest(RunningAction,guiplugins.ActionTabGUI):
    def __init__(self, allApps, *args):
        guiplugins.ActionTabGUI.__init__(self, allApps, *args)
        self.currentApp = None
        self.recordTime = None
        defaultVersion, defaultCheckout = "", ""
        if len(allApps) > 0:
            self.currentApp = allApps[0]
            defaultVersion = self.currentApp.getFullVersion(forSave=1)
            defaultCheckout = self.currentApp.checkout
        self.addOption("v", "Version to record", defaultVersion)
        self.addOption("c", "Checkout to use for recording", defaultCheckout)
        self.addSwitch("rectraffic", "Also record command-line or client-server traffic", 1)
        self.addSwitch("rep", "Automatically replay test after recording it", 1)
        self.addSwitch("repgui", options = ["Auto-replay invisible", "Auto-replay in dynamic GUI"])
    def correctTestClass(self):
        return "test-case"
    def _getStockId(self):
        return "media-record"
    def getTabTitle(self):
        return "Recording"
    def messageAfterPerform(self):
        return "Started record session for " + self.describeTests()
    def performOnCurrent(self):
        self.updateRecordTime(self.currTestSelection[0])
        self.startTextTestProcess("record", [ "-g", "-record" ])
    def shouldShow(self):
        return len(self.validApps) > 0 # override the default so it's disabled if there are no apps
    def isValidForApp(self, app):
        return app.getConfigValue("use_case_record_mode") != "disabled" and \
               app.getConfigValue("use_case_recorder") != "none"
    def updateOptions(self):
        if self.currentApp is not self.currAppSelection[0]:
            self.currentApp = self.currAppSelection[0]
            self.optionGroup.setOptionValue("v", self.currentApp.getFullVersion(forSave=1))
            self.optionGroup.setOptionValue("c", self.currentApp.checkout)
            return True
        else:
            return False
    def getUseCaseFile(self, test):
        return test.getFileName("usecase", self.optionGroup.getOptionValue("v"))
    def updateRecordTime(self, test):
        file = self.getUseCaseFile(test)
        if file:
            self._updateRecordTime(file)
    def _updateRecordTime(self, file):
        newTime = plugins.modifiedTime(file)
        if newTime != self.recordTime:
            self.recordTime = newTime
            outerRecord = os.getenv("USECASE_RECORD_SCRIPT")
            if outerRecord:
                # If we have an "outer" record going on, provide the result as a target recording...
                target = plugins.addLocalPrefix(outerRecord, "target_record")
                shutil.copyfile(file, target)
            return True
        else:
            return False
    def getChangedUseCaseVersion(self, test):
        test.refreshFiles() # update cache after record run
        file = self.getUseCaseFile(test)
        if not file or not self._updateRecordTime(file):
            return

        parts = os.path.basename(file).split(".")
        return ".".join(parts[2:])
    def getMultipleTestWarning(self):
        return "record " + self.describeTests() + " simultaneously"

    def handleCompletion(self, testSel, usecase):
        test = testSel[0]
        if usecase == "record":
            changedUseCaseVersion = self.getChangedUseCaseVersion(test)
            if changedUseCaseVersion is not None and self.optionGroup.getSwitchValue("rep"):
                self.startTextTestProcess("replay", self.getReplayRunModeOptions(changedUseCaseVersion))
                message = "Recording completed for " + repr(test) + \
                          ". Auto-replay of test now started. Don't submit the test manually!"
                self.notify("Status", message)
            else:
                self.notify("Status", "Recording completed for " + repr(test) + ", not auto-replaying")
        else:
            self.notify("Status", "Recording and auto-replay completed for " + repr(test))

    def getCommandLineKeys(self, usecase):
        keys = [ "v", "c" ]
        if usecase == "record":
            keys.append("rectraffic")
        return keys

    def getReplayRunModeOptions(self, overwriteVersion):
        if self.optionGroup.getSwitchValue("repgui"):
            return [ "-autoreplay", "-g" ]
        else:
            return [ "-autoreplay", "-o", overwriteVersion ]

    def _getTitle(self):
        return "Record _Use-Case"


class ImportFiles(guiplugins.ActionDialogGUI):
    def __init__(self, allApps, *args):
        self.creationDir = None
        self.appendAppName = False
        self.currentStem = ""
        self.fileChooser = None
        guiplugins.ActionDialogGUI.__init__(self, allApps, *args)
        self.addOption("stem", "Type of file/directory to create", allocateNofValues=2)
        self.addOption("v", "Version identifier to use")
        possibleDirs = self.getPossibleDirs(allApps)
        # The point of this is that it's never sensible as the source for anything, so it serves as a "use the parent" option
        # for back-compatibility
        self.addSwitch("act", options=[ "Import file/directory from source", "Create a new file", "Create a new directory" ])
        self.addOption("src", "Source to copy from", selectFile=True, possibleDirs=possibleDirs)
        
    def getPossibleDirs(self, allApps):
        if len(allApps) > 0:
            return sorted(set((app.getDirectory() for app in allApps)))
        else:
            return [ os.getenv("TEXTTEST_HOME") ]
                
    def singleTestOnly(self):
        return True
    def _getTitle(self):
        return "Create/_Import"
    def getTooltip(self):
        return "Create a new file or directory, possibly by copying it" 
    def _getStockId(self):
        return "new"
    def getDialogTitle(self):
        return "Create/Import Files and Directories"
    def isActiveOnCurrent(self, *args):
        return self.creationDir is not None and guiplugins.ActionDialogGUI.isActiveOnCurrent(self, *args)
    def getResizeDivisors(self):
        # size of the dialog
        return 1.4, 1.4
    def getSignalsSent(self):
        return [ "NewFile" ]
    def messageAfterPerform(self):
        pass

    def updateOptions(self):
        self.currentStem = ""
        return False

    def fillVBox(self, vbox):
        test = self.currTestSelection[0]
        dirText = self.getDirectoryText(test)
        self.addText(vbox, "<b><u>" + dirText + "</u></b>")
        self.addText(vbox, "<i>(Test is " + repr(test) + ")</i>")
        return guiplugins.ActionDialogGUI.fillVBox(self, vbox)

    def stemChanged(self, *args):
        option = self.optionGroup.getOption("stem")
        newStem = option.getValue()    
        if newStem in option.possibleValues and newStem != self.currentStem:
            self.currentStem = newStem
            version = self.optionGroup.getOptionValue("v")
            sourcePath = self.getDefaultSourcePath(newStem, version)
            self.optionGroup.setValue("src", sourcePath)

    def actionChanged(self, *args):
        if self.fileChooser:
            self.setFileChooserSensitivity(verbose=True)

    def setFileChooserSensitivity(self, verbose):
        action = self.optionGroup.getValue("act")
        sensitive = self.fileChooser.get_property("sensitive")
        newSensitive = action == 0
        if newSensitive != sensitive:
            self.fileChooser.set_property("sensitive", newSensitive)
            if verbose:
                guiplugins.guilog.info("Sensitivity of source file chooser changed to " + repr(newSensitive))
        
    def getTargetPath(self, *args, **kwargs):
        targetPathName = self.getFileName(*args, **kwargs)
        return os.path.join(self.creationDir, targetPathName)
        
    def getDefaultSourcePath(self, stem, version):
        targetPath = self.getTargetPath(stem, version)
        test = self.currTestSelection[0]
        pathNames = test.getAllPathNames(stem, refVersion=version)
        if len(pathNames) > 0:
            firstSource = pathNames[-1]
            if os.path.basename(firstSource).startswith(stem + "." + test.app.name):
                targetPath = self.getTargetPath(stem, version, appendAppName=True)
            if firstSource != targetPath:
                return firstSource
            elif len(pathNames) > 1:
                return pathNames[-2]
        return test.getDirectory()

    def createComboBox(self, *args):
        combobox, entry = guiplugins.ActionDialogGUI.createComboBox(self, *args)
        handler = combobox.connect("changed", self.stemChanged)
        return combobox, entry

    def createRadioButtons(self, *args):
        buttons = guiplugins.ActionDialogGUI.createRadioButtons(self, *args)
        buttons[0].connect("toggled", self.actionChanged)
        return buttons

    def createFileChooser(self, *args):
        self.fileChooser = guiplugins.ActionDialogGUI.createFileChooser(self, *args)
        self.setFileChooserSensitivity(verbose=False) # Check initial values, maybe set insensitive
        return self.fileChooser
    
    def addText(self, vbox, text):
        header = gtk.Label()
        guiplugins.guilog.info("Adding text '" + text + "'")
        header.set_markup(text + "\n")
        vbox.pack_start(header, expand=False, fill=False)
    
    def getDirectoryText(self, test):
        relDir = plugins.relpath(self.creationDir, test.getDirectory())
        if relDir:
            return "Create or import files in test subdirectory '" + relDir + "'"
        else:
            return "Create or import files in the test directory"

    def notifyFileCreationInfo(self, creationDir, fileType):
        self.fileChooser = None
        if fileType == "external":
            self.creationDir = None
            self.setSensitivity(False)
        else:
            self.creationDir = creationDir
            newActive = creationDir is not None
            self.setSensitivity(newActive)
            if newActive:
                self.updateStems(fileType)
                self.appendAppName = (fileType == "definition" or fileType == "standard")
                self.optionGroup.setValue("act", int(self.appendAppName))

    def findAllStems(self, fileType):
        if fileType == "definition":
            return self.getDefinitionFiles()
        elif fileType == "data":
            return self.currTestSelection[0].app.getDataFileNames()
        elif fileType == "standard":
            return self.getStandardFiles()
        else:
            return []

    def getDefinitionFiles(self):
        defFiles = []
        defFiles.append("environment")
        if self.currTestSelection[0].classId() == "test-case":
            defFiles.append("options")
            recordMode = self.currTestSelection[0].getConfigValue("use_case_record_mode")
            if recordMode == "disabled":
                defFiles.append("input")
            else:
                defFiles.append("usecase")
        # We only want to create files this way that
        # (a) are not created and understood by TextTest itself ("builtin")
        # (b) are not auto-generated ("regenerate")
        # That leaves the rest ("default")
        return defFiles + self.currTestSelection[0].defFileStems("default")

    def getStandardFiles(self):
        collateKeys = self.currTestSelection[0].getConfigValue("collate_file").keys()
        # Don't pick up "dummy" indicators on Windows...
        stdFiles = [ "output", "errors" ] + filter(lambda k: k, collateKeys)
        discarded = [ "stacktrace" ] + self.currTestSelection[0].getConfigValue("discard_file")
        return filter(lambda f: f not in discarded, stdFiles)

    def updateStems(self, fileType):
        stems = self.findAllStems(fileType)
        if len(stems) > 0:
            self.optionGroup.setValue("stem", stems[0])
        else:
            self.optionGroup.setValue("stem", "")
        self.optionGroup.setPossibleValues("stem", stems)

    def getFileName(self, stem, version, appendAppName=False):
        fileName = stem
        if self.appendAppName or appendAppName:
            fileName += "." + self.currTestSelection[0].app.name
        if version:
            fileName += "." + version
        return fileName

    def performOnCurrent(self):
        stem = self.optionGroup.getOptionValue("stem")
        version = self.optionGroup.getOptionValue("v")
        action = self.optionGroup.getSwitchValue("act")
        test = self.currTestSelection[0]
        if action > 0: # Create new
            targetPath = self.getTargetPath(stem, version)
            if os.path.exists(targetPath):
                raise plugins.TextTestError, "Not creating file or directory : path already exists:\n" + targetPath

            if action == 1:
                plugins.ensureDirExistsForFile(targetPath)
                file = open(targetPath, "w")
                file.close()
                guiplugins.guilog.info("Creating new empty file...")
                self.notify("NewFile", targetPath, False)
            elif action == 2:
                plugins.ensureDirectoryExists(targetPath)
                guiplugins.guilog.info("Creating new empty directory...")
                test.filesChanged()
        else:
            sourcePath = self.optionGroup.getOptionValue("src")
            appendAppName = os.path.basename(sourcePath).startswith(stem + "." + test.app.name)
            targetPath = self.getTargetPath(stem, version, appendAppName) 
            fileExisted = os.path.exists(targetPath)
            guiplugins.guilog.info("Creating new path, copying " + sourcePath)
            plugins.copyPath(sourcePath, targetPath)
            self.notify("NewFile", targetPath, fileExisted)


class RemoveTests(guiplugins.ActionGUI):
    def notifyFileCreationInfo(self, creationDir, fileType):
        canRemove = fileType != "external" and \
                    (creationDir is None or len(self.currFileSelection) > 0) and \
                    self.isActiveOnCurrent()
        self.setSensitivity(canRemove)

    def isActiveOnCurrent(self, *args):
        for test in self.currTestSelection:
            if test.parent:
                return True
        # Only root selected. Any file?
        if len(self.currFileSelection) > 0:
            return True
        else:
            return False

    def _getTitle(self):
        return "Remove..."

    def _getStockId(self):
        return "delete"

    def getTooltip(self):
        return "Remove selected files"

    def getTestCountDescription(self):
        desc = self.pluralise(self.distinctTestCount, "test")
        diff = len(self.currTestSelection) - self.distinctTestCount
        if diff > 0:
            desc += " (with " + self.pluralise(diff, "extra instance") + ")"
        return desc

    def updateSelection(self, tests, apps, rowCount, *args):
        self.distinctTestCount = rowCount
        return guiplugins.ActionGUI.updateSelection(self, tests, apps, rowCount, *args)

    def getFileRemoveWarning(self):
        return "This will remove files from the file system and hence may not be reversible."
        
    def getConfirmationMessage(self):
        extraLines = "\n\nNote: " + self.getFileRemoveWarning() + "\n\nAre you sure you wish to proceed?\n"""
        currTest = self.currTestSelection[0]
        if len(self.currFileSelection) > 0:
            return "\nYou are about to remove " + self.pluralise(len(self.currFileSelection), self.getType(self.currFileSelection[0][0])) + \
                   " from the " + currTest.classDescription() + " '" + currTest.name + "'." + extraLines
        elif len(self.currTestSelection) == 1:
            if currTest.classId() == "test-case":
                return "\nYou are about to remove the test '" + currTest.name + \
                       "' and all associated files." + extraLines
            else:
                return "\nYou are about to remove the entire test suite '" + currTest.name + \
                       "' and all " + str(currTest.size()) + " tests that it contains." + extraLines
        else:
            return "\nYou are about to remove " + self.getTestCountDescription() + \
                   " and all associated files." + extraLines

    def performOnCurrent(self):
        if len(self.currFileSelection) > 0:
            self.removeFiles()
        else:
            self.removeTests()

    def getTestsToRemove(self, list):
        toRemove = []
        warnings = ""
        for test in list:
            if not test.parent:
                warnings += "\nThe root suite\n'" + test.name + " (" + test.app.name + ")'\ncannot be removed.\n"
                continue
            if test.classId() == "test-suite":
                subTests, subWarnings = self.getTestsToRemove(test.testcases)
                warnings += subWarnings
                for subTest in subTests:
                    if not subTest in toRemove:
                        toRemove.append(subTest)
            if not test in toRemove:
                toRemove.append(test)

        return toRemove, warnings

    def removeTests(self):
        namesRemoved = []
        toRemove, warnings = self.getTestsToRemove(self.currTestSelection)
        permMessage = "Failed to remove test: didn't have sufficient write permission to the test files"
        for test in toRemove:
            dir = test.getDirectory()
            if os.path.isdir(dir):
                plugins.tryFileChange(self.removePath, permMessage, dir)
            if plugins.tryFileChange(test.remove, permMessage):
                namesRemoved.append(test.name)
        self.notify("Status", "Removed test(s) " + ",".join(namesRemoved))
        if warnings:
            self.showWarningDialog(warnings)

    @staticmethod
    def removePath(dir):
        return plugins.removePath(dir)
    
    def getType(self, filePath):
        if os.path.isdir(filePath):
            return "directory"
        else:
            return "file"

    def removeFiles(self):
        test = self.currTestSelection[0]
        warnings = ""
        removed = 0
        for filePath, comparison in self.currFileSelection:
            fileType = self.getType(filePath)
            self.notify("Status", "Removing " + fileType + " " + os.path.basename(filePath))
            self.notify("ActionProgress", "")
            permMessage = "Insufficient permissions to remove " + fileType + " '" + filePath + "'"
            if plugins.tryFileChange(self.removePath, permMessage, filePath):
                removed += 1

        test.filesChanged()
        self.notify("Status", "Removed " + self.pluralise(removed, fileType) + " from the " +
                    test.classDescription() + " " + test.name + "")
        if warnings:
            self.showWarningDialog(warnings)

    def messageAfterPerform(self):
        pass # do it as part of the method as currentTest will have changed by the end!


class ReportBugs(guiplugins.ActionDialogGUI):
    def __init__(self, *args):
        guiplugins.ActionDialogGUI.__init__(self, *args)
        self.addOption("search_string", "Text or regexp to match")
        self.addOption("search_file", "File to search in")
        self.addOption("version", "\nVersion to report for")
        self.addOption("execution_hosts", "Trigger only when run on machine(s)")
        self.addOption("bug_system", "\nExtract info from bug system", "<none>", [ "bugzilla", "bugzillav2" ])
        self.addOption("bug_id", "Bug ID (only if bug system given)")
        self.addOption("full_description", "\nFull description (no bug system)")
        self.addOption("brief_description", "Few-word summary (no bug system)")
        self.addSwitch("trigger_on_absence", "Trigger if given text is NOT present")
        self.addSwitch("ignore_other_errors", "Trigger even if other files differ")
        self.addSwitch("trigger_on_success", "Trigger even if test would otherwise succeed")
        self.addSwitch("internal_error", "Report as 'internal error' rather than 'known bug' (no bug system)")
    def _getStockId(self):
        return "info"
    def singleTestOnly(self):
        return True
    def _getTitle(self):
        return "Enter Failure Information"
    def getDialogTitle(self):
        return "Enter information for automatic interpretation of test failures"
    def updateOptions(self):
        self.optionGroup.setOptionValue("search_file", self.currTestSelection[0].app.getConfigValue("log_file"))
        self.optionGroup.setPossibleValues("search_file", self.getPossibleFileStems())
        self.optionGroup.setOptionValue("version", self.currTestSelection[0].app.getFullVersion())
        return False
    def getPossibleFileStems(self):
        stems = []
        for test in self.currTestSelection[0].testCaseList():
            for stem in test.dircache.findAllStems(self.currTestSelection[0].defFileStems()):
                if not stem in stems:
                    stems.append(stem)
        # use for unrunnable tests...
        stems.append("free_text")
        return stems
    def checkSanity(self):
        if len(self.optionGroup.getOptionValue("search_string")) == 0:
            raise plugins.TextTestError, "Must fill in the field 'text or regexp to match'"
        if self.optionGroup.getOptionValue("bug_system") == "<none>":
            if len(self.optionGroup.getOptionValue("full_description")) == 0 or \
                   len(self.optionGroup.getOptionValue("brief_description")) == 0:
                raise plugins.TextTestError, "Must either provide a bug system or fill in both description and summary fields"
        else:
            if len(self.optionGroup.getOptionValue("bug_id")) == 0:
                raise plugins.TextTestError, "Must provide a bug ID if bug system is given"
    def versionSuffix(self):
        version = self.optionGroup.getOptionValue("version")
        if len(version) == 0:
            return ""
        else:
            return "." + version
    def getFileName(self):
        name = "knownbugs." + self.currTestSelection[0].app.name + self.versionSuffix()
        return os.path.join(self.currTestSelection[0].getDirectory(), name)
    def getResizeDivisors(self):
        # size of the dialog
        return 1.4, 1.7
    def performOnCurrent(self):
        self.checkSanity()
        fileName = self.getFileName()
        writeFile = open(fileName, "a")
        writeFile.write("\n[Reported by " + os.getenv("USER", "Windows") + " at " + plugins.localtime() + "]\n")
        for name, option in self.optionGroup.options.items():
            value = option.getValue()
            if name != "version" and value and value != "<none>":
                writeFile.write(name + ":" + str(value) + "\n")
        writeFile.close()
        self.currTestSelection[0].filesChanged()

class RecomputeTests(guiplugins.ActionGUI):
    def __init__(self, *args):
        guiplugins.ActionGUI.__init__(self, *args)
        self.latestNumberOfRecomputations = 0
    def isActiveOnCurrent(self, test=None, state=None):
        for currTest in self.currTestSelection:
            if currTest is test:
                if state.hasStarted():
                    return True
            elif currTest.state.hasStarted():
                return True
        return False
    def _getTitle(self):
        return "Recompute Status"
    def _getStockId(self):
        return "refresh"
    def getTooltip(self):
        return "Recompute test status, including progress information if appropriate"
    def getSignalsSent(self):
        return [ "Recomputed" ]
    def messageAfterPerform(self):
        if self.latestNumberOfRecomputations == 0:
            return "No test needed recomputation."
        else:
            return "Recomputed status of " + self.pluralise(self.latestNumberOfRecomputations, "test") + "."
    def performOnCurrent(self):
        self.latestNumberOfRecomputations = 0
        for app in self.currAppSelection:
            self.notify("Status", "Rereading configuration for " + repr(app) + " ...")
            self.notify("ActionProgress", "")
            app.setUpConfiguration()

        for test in self.currTestSelection:
            self.latestNumberOfRecomputations += 1
            self.notify("Status", "Recomputing status of " + repr(test) + " ...")
            self.notify("ActionProgress", "")
            test.app.recomputeProgress(test, self.observers)
            self.notify("Recomputed", test)


class RefreshAll(guiplugins.BasicActionGUI):
    def __init__(self, *args):
        guiplugins.BasicActionGUI.__init__(self, *args)
        self.rootTestSuites = []
    def _getTitle(self):
        return "Refresh"
    def _getStockId(self):
        return "refresh"
    def getTooltip(self):
        return "Refresh the whole test suite so that it reflects file changes"
    def messageBeforePerform(self):
        return "Refreshing the whole test suite..."
    def messageAfterPerform(self):
        return "Refreshed the test suite from the files"
    def addSuites(self, suites):
        self.rootTestSuites += suites
    def performOnCurrent(self):
        for suite in self.rootTestSuites:
            self.notify("ActionProgress", "")
            suite.app.setUpConfiguration()
            self.notify("ActionProgress", "")
            filters = suite.app.getFilterList(self.rootTestSuites)
            suite.refresh(filters)


class SortTestSuiteFileAscending(guiplugins.ActionGUI):
    def singleTestOnly(self):
        return True
    def correctTestClass(self):
        return "test-suite"
    def isActiveOnCurrent(self, *args):
        return guiplugins.ActionGUI.isActiveOnCurrent(self, *args) and not self.currTestSelection[0].autoSortOrder
    def _getStockId(self):
        return "sort-ascending"
    def _getTitle(self):
        return "_Sort Test Suite File"
    def messageAfterPerform(self):
        return "Sorted testsuite file for " + self.describeTests() + " in alphabetical order."
    def getTooltip(self):
        return "sort testsuite file for the selected test suite in alphabetical order"
    def performOnCurrent(self):
        self.performRecursively(self.currTestSelection[0], True)
    def performRecursively(self, suite, ascending):
        # First ask all sub-suites to sort themselves
        errors = ""
        if guiplugins.guiConfig.getValue("sort_test_suites_recursively"):
            for test in suite.testcases:
                if test.classId() == "test-suite":
                    try:
                        self.performRecursively(test, ascending)
                    except Exception, e:
                        errors += str(e) + "\n"

        self.notify("Status", "Sorting " + repr(suite))
        self.notify("ActionProgress", "")
        if self.hasNonDefaultTests():
            self.showWarningDialog("\nThe test suite\n'" + suite.name + "'\ncontains tests which are not present in the default version.\nTests which are only present in some versions will not be\nmixed with tests in the default version, which might lead to\nthe suite not looking entirely sorted.")

        suite.sortTests(ascending)
    def hasNonDefaultTests(self):
        if len(self.currTestSelection) == 1:
            return False

        for extraSuite in self.currTestSelection[1:]:
            for test in extraSuite.testcases:
                if not self.currTestSelection[0].findSubtest(test.name):
                    return True
        return False

class SortTestSuiteFileDescending(SortTestSuiteFileAscending):
    def _getStockId(self):
        return "sort-descending"
    def _getTitle(self):
        return "_Reversed Sort Test Suite File"
    def messageAfterPerform(self):
        return "Sorted testsuite file for " + self.describeTests() + " in reversed alphabetical order."
    def getTooltip(self):
        return "sort testsuite file for the selected test suite in reversed alphabetical order"
    def performOnCurrent(self):
        self.performRecursively(self.currTestSelection[0], False)

class RepositionTest(guiplugins.ActionGUI):
    def singleTestOnly(self):
        return True
    def _isActiveOnCurrent(self):
        return guiplugins.ActionGUI.isActiveOnCurrent(self) and \
               self.currTestSelection[0].parent and \
               not self.currTestSelection[0].parent.autoSortOrder
    def getSignalsSent(self):
        return [ "RefreshTestSelection" ]

    def performOnCurrent(self):
        newIndex = self.findNewIndex()
        test = self.currTestSelection[0]
        permMessage = "Failed to reposition test: no permissions to edit the testsuite file"
                
        if plugins.tryFileChange(test.parent.repositionTest, permMessage, test, newIndex):
            self.notify("RefreshTestSelection")
        else:
            raise plugins.TextTestError, "\nThe test\n'" + test.name + "'\nis not present in the default version\nand hence cannot be reordered.\n"

class RepositionTestDown(RepositionTest):
    def _getStockId(self):
        return "go-down"
    def _getTitle(self):
        return "Move down"
    def messageAfterPerform(self):
        return "Moved " + self.describeTests() + " one step down in suite."
    def getTooltip(self):
        return "Move selected test down in suite"
    def findNewIndex(self):
        return min(self.currTestSelection[0].positionInParent() + 1, self.currTestSelection[0].parent.maxIndex())
    def isActiveOnCurrent(self, *args):
        if not self._isActiveOnCurrent():
            return False
        return self.currTestSelection[0].parent.testcases[self.currTestSelection[0].parent.maxIndex()] != self.currTestSelection[0]

class RepositionTestUp(RepositionTest):
    def _getStockId(self):
        return "go-up"
    def _getTitle(self):
        return "Move up"
    def messageAfterPerform(self):
        return "Moved " + self.describeTests() + " one step up in suite."
    def getTooltip(self):
        return "Move selected test up in suite"
    def findNewIndex(self):
        return max(self.currTestSelection[0].positionInParent() - 1, 0)
    def isActiveOnCurrent(self, *args):
        if not self._isActiveOnCurrent():
            return False
        return self.currTestSelection[0].parent.testcases[0] != self.currTestSelection[0]

class RepositionTestFirst(RepositionTest):
    def _getStockId(self):
        return "goto-top"
    def _getTitle(self):
        return "Move to first"
    def messageAfterPerform(self):
        return "Moved " + self.describeTests() + " to first in suite."
    def getTooltip(self):
        return "Move selected test to first in suite"
    def findNewIndex(self):
        return 0
    def isActiveOnCurrent(self, *args):
        if not self._isActiveOnCurrent():
            return False
        return self.currTestSelection[0].parent.testcases[0] != self.currTestSelection[0]

class RepositionTestLast(RepositionTest):
    def _getStockId(self):
        return "goto-bottom"
    def _getTitle(self):
        return "Move to last"
    def messageAfterPerform(self):
        return "Moved " + repr(self.currTestSelection[0]) + " to last in suite."
    def getTooltip(self):
        return "Move selected test to last in suite"
    def findNewIndex(self):
        return self.currTestSelection[0].parent.maxIndex()
    def isActiveOnCurrent(self, *args):
        if not self._isActiveOnCurrent():
            return False
        currLastTest = self.currTestSelection[0].parent.testcases[len(self.currTestSelection[0].parent.testcases) - 1]
        return currLastTest != self.currTestSelection[0]

class RenameTest(guiplugins.ActionDialogGUI):
    def __init__(self, *args):
        guiplugins.ActionDialogGUI.__init__(self, *args)
        self.addOption("name", "\nNew name")
        self.addOption("desc", "\nNew description")
        self.oldName = ""
        self.oldDescription = ""
    def isActiveOnCurrent(self, *args):
        # Don't allow renaming of the root suite
        return guiplugins.ActionGUI.isActiveOnCurrent(self, *args) and bool(self.currTestSelection[0].parent)
    def singleTestOnly(self):
        return True
    def updateOptions(self):
        self.oldName = self.currTestSelection[0].name
        self.oldDescription = plugins.extractComment(self.currTestSelection[0].description)
        self.optionGroup.setOptionValue("name", self.oldName)
        self.optionGroup.setOptionValue("desc", self.oldDescription)
        return True
    def fillVBox(self, vbox):
        header = gtk.Label()
        header.set_markup("<b>" + plugins.convertForMarkup(self.oldName) + "</b>")
        vbox.pack_start(header, expand=False, fill=False)
        return guiplugins.ActionDialogGUI.fillVBox(self, vbox)
    def _getStockId(self):
        return "italic"
    def _getTitle(self):
        return "_Rename..."
    def getTooltip(self):
        return "Rename selected test"
    def messageAfterPerform(self):
        pass # Use method below instead.

    def getNameChangeMessage(self, newName):    
        return "Renamed test " + self.oldName + " to " + newName

    def getChangeMessage(self, newName, newDesc):
        if self.oldName != newName:
            message = self.getNameChangeMessage(newName)
            if self.oldDescription != newDesc:
                message += " and changed description."
            else:
                message += "."
        elif newDesc != self.oldDescription:
            message = "Changed description of test " + self.oldName + "."
        else:
            message = "Nothing changed."
        return message
    def checkNewName(self, newName):
        if len(newName) == 0:
            raise plugins.TextTestError, "Please enter a new name."
        if newName.find(" ") != -1:
            raise plugins.TextTestError, "The new name must not contain spaces, please choose another name."
        if newName != self.oldName:
            for test in self.currTestSelection[0].parent.testCaseList():
                if test.name == newName:
                    raise plugins.TextTestError, "The name '" + newName + "' is already taken, please choose another name."
            newDir = os.path.join(self.currTestSelection[0].parent.getDirectory(), newName)
            if os.path.isdir(newDir):
                self.handleExistingDirectory(newDir)

    def handleExistingDirectory(self, newDir): # In CVS we might need to override this...
        raise plugins.TextTestError, "The directory " + newDir + " already exists, please choose another name."

    def performOnCurrent(self):
        try:
            newName = self.optionGroup.getOptionValue("name")
            self.checkNewName(newName)
            newDesc = self.optionGroup.getOptionValue("desc")
            if newName != self.oldName or newDesc != self.oldDescription:
                for test in self.currTestSelection:
                    # Do this first, so that if we fail we won't update the test suite files either
                    self.moveFiles(test, newName)
                    test.rename(newName, newDesc)
            changeMessage = self.getChangeMessage(newName, newDesc)
            self.oldName = newName
            self.oldDescription = newDesc
            self.notify("Status", changeMessage)
        except IOError, e:
            self.showErrorDialog("Failed to rename test:\n" + str(e))
        except OSError, e:
            self.showErrorDialog("Failed to rename test:\n" + str(e))

    def moveFiles(self, test, newName):
        # Create new directory, copy files if the new name is new (we might have
        # changed only the comment ...)
        if test.name != newName:
            oldDir = test.getDirectory()
            newDir = test.parent.getNewDirectoryName(newName)
            if os.path.isdir(oldDir):
                self.moveDirectory(oldDir, newDir)

    @staticmethod
    def moveDirectory(oldDir, newDir):
        # overridden by version control modules
        os.rename(oldDir, newDir)


class ShowFileProperties(guiplugins.ActionResultDialogGUI):
    def __init__(self, allApps, dynamic):
        self.dynamic = dynamic
        guiplugins.ActionGUI.__init__(self, allApps)
    def _getStockId(self):
        return "properties"
    def isActiveOnCurrent(self, *args):
        return ((not self.dynamic) or len(self.currTestSelection) == 1) and \
               len(self.currFileSelection) > 0
    def _getTitle(self):
        return "_File Properties"
    def getTooltip(self):
        return "Show properties of selected files"
    def describeTests(self):
        return str(len(self.currFileSelection)) + " files"
    def getAllProperties(self):
        errors, properties = [], []
        for file, comp in self.currFileSelection:
            if self.dynamic and comp:
                self.processFile(comp.tmpFile, properties, errors)
            self.processFile(file, properties, errors)

        if len(errors):
            self.showErrorDialog("Failed to get file properties:\n" + "\n".join(errors))

        return properties
    def processFile(self, file, properties, errors):
        try:
            prop = plugins.FileProperties(file)
            properties.append(prop)
        except Exception, e:
            errors.append(plugins.getExceptionString())

    # xalign = 1.0 means right aligned, 0.0 means left aligned
    def justify(self, text, xalign = 0.0):
        alignment = gtk.Alignment()
        alignment.set(xalign, 0.0, 0.0, 0.0)
        label = gtk.Label(text)
        alignment.add(label)
        return alignment

    def addContents(self):
        dirToProperties = {}
        props = self.getAllProperties()
        for prop in props:
            dirToProperties.setdefault(prop.dir, []).append(prop)
        vbox = self.createVBox(dirToProperties)
        self.dialog.vbox.pack_start(vbox, expand=True, fill=True)
        return "\n".join([ prop.getDescription() for prop in props ])

    def createVBox(self, dirToProperties):
        vbox = gtk.VBox()
        for dir, properties in dirToProperties.items():
            expander = gtk.Expander()
            expander.set_label_widget(self.justify(dir))
            table = gtk.Table(len(properties), 7)
            table.set_col_spacings(5)
            row = 0
            for prop in properties:
                values = prop.getUnixRepresentation()
                table.attach(self.justify(values[0] + values[1], 1.0), 0, 1, row, row + 1)
                table.attach(self.justify(values[2], 1.0), 1, 2, row, row + 1)
                table.attach(self.justify(values[3], 0.0), 2, 3, row, row + 1)
                table.attach(self.justify(values[4], 0.0), 3, 4, row, row + 1)
                table.attach(self.justify(values[5], 1.0), 4, 5, row, row + 1)
                table.attach(self.justify(values[6], 1.0), 5, 6, row, row + 1)
                table.attach(self.justify(prop.filename, 0.0), 6, 7, row, row + 1)
                row += 1
            hbox = gtk.HBox()
            hbox.pack_start(table, expand=False, fill=False)
            innerBorder = gtk.Alignment()
            innerBorder.set_padding(5, 0, 0, 0)
            innerBorder.add(hbox)
            expander.add(innerBorder)
            expander.set_expanded(True)
            border = gtk.Alignment()
            border.set_padding(5, 5, 5, 5)
            border.add(expander)
            vbox.pack_start(border, expand=False, fill=False)
        return vbox


class InteractiveActionConfig:
    def getMenuNames(self):
        return [ "file", "edit", "view", "actions", "reorder", "help" ]

    def getInteractiveActionClasses(self, dynamic):
        classes = [ Quit, ViewTestFileInEditor, ShowFileProperties ]
        if dynamic:
            classes += [ ViewFilteredTestFileInEditor, ViewOrigFileInEditor, ViewFilteredOrigFileInEditor,
                         ViewFileDifferences, ViewFilteredFileDifferences, FollowFile,
                         SaveTests, SaveSelection, KillTests, AnnotateGUI,
                         MarkTest, UnmarkTest, RecomputeTests ] # must keep RecomputeTests at the end!
        else:
            classes += [ ViewConfigFileInEditor, CopyTests, CutTests,
                         PasteTests, ImportTestCase, ImportTestSuite, ImportApplication,
                         ImportFiles, ReportBugs, SelectTests,
                         RefreshAll, HideUnselected, HideSelected, ShowAll,
                         RunTestsBasic, RunTestsAdvanced, RecordTest, ResetGroups, RenameTest, RemoveTests,
                         SortTestSuiteFileAscending, SortTestSuiteFileDescending,
                         RepositionTestFirst, RepositionTestUp,
                         RepositionTestDown, RepositionTestLast,
                         ReconnectToTests, LoadSelection, SaveSelection ]
        classes += [ helpdialogs.ShowMigrationNotes, helpdialogs.ShowChangeLogs, helpdialogs.ShowVersions, helpdialogs.AboutTextTest ]
        return classes

    def getReplacements(self):
        # Return a dictionary mapping classes above to what to replace them with
        return {}

    def isValid(self, className):
        replacements = self.getReplacements()
        if className in replacements.values():
            return True
        elif replacements.has_key(className):
            return False
        else:
            return className in self.getInteractiveActionClasses(True) or className in self.getInteractiveActionClasses(False)

    def getColourDictionary(self):
        dict = {}
        dict["default"] = "red"
        dict["success"] = "green"
        dict["failure"] = "red"
        dict["running"] = "yellow"
        dict["not_started"] = "white"
        dict["pending"] = "white"
        dict["static"] = "grey90"
        dict["marked"] = "orange"
        return dict

    def getDefaultAccelerators(self):
        dict = {}
        dict["quit"] = "<control>q"
        dict["select"] = "<control>s"
        dict["filter"] = "<control>f"
        dict["save"] = "<control>s"
        dict["save_as"] = "<control><alt>s"
        dict["copy"] = "<control>c"
        dict["kill"] = "<control>Delete"
        dict["remove"] = "<control>Delete"
        dict["cut"] = "<control>x"
        dict["paste"] = "<control>v"
        dict["save_selection"] = "<control>d"
        dict["load_selection"] = "<control><shift>o"
        dict["reset"] = "<control>e"
        dict["reconnect"] = "<control><shift>r"
        dict["run"] = "<control>r"
        dict["rename"] = "<control>m"
        dict["refresh"] = "F5"
        dict["record_use-case"] = "F9"
        dict["recompute_status"] = "F5"
        dict["add_test"] = "<control>n"
        dict["enter_failure_information"] = "<control>i"
        dict["move_down"] = "<control>Page_Down"
        dict["move_up"] = "<control>Page_Up"
        dict["move_to_first"] = "<control>Home"
        dict["move_to_last"] = "<control>End"
        dict["mark"] = "<control><shift>m"
        dict["unmark"] = "<control><shift>u"
        return dict

class DocumentGUIConfig(plugins.Action):
    def setUpApplication(self, app):
        guiConfig = guiplugins.GUIConfig(False, [ app ], None)
        for key in sorted(guiConfig.configDir.keys()):
            docOutput = guiConfig.configDocs[key]
            value = guiConfig.configDir[key]
            print key + "|" + str(value) + "|" + docOutput
