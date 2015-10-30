#!/usr/bin/python

#
# This script will search the required Test drivers into the '--pom' parameter file
# that need to be used to run the tests for the specified q-tests passed on '--paths'.
#

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET


def load_properties(filepath, sep='=', comment_char='#'):
    """
    Read the file passed as parameter as a properties file.
    """
    props = {}
    with open(filepath, "rt") as f:
        for line in f:
            l = line.strip()
            if l and not l.startswith(comment_char):
                if l.endswith("\\"):
                    l = l.strip("\\")

                key_value = l.split(sep)

                if len(key_value) == 1:
                    props_val = props_val + key_value[0].strip()
                else:
                    props_key = key_value[0].strip()
                    props_val = key_value[1].strip('" \t"')

                props[props_key] = props_val

    return props

def replace_vars(line, propsVars):
    for var in propsVars:
        line = line.replace("${" + var + "}", propsVars[var])
    return line

#
# Find all <qtestgen ... /> sections from the pom.xml file.
#
def find_qtestgen(pomtree):
    PREFIX_XMLNS = "{http://maven.apache.org/POM/4.0.0}"

    '''
    Example of a XML structure to find:

    <build>
     <plugins>
       <plugin>
         <groupId>org.apache.maven.plugins</groupId>
         ...
         <executions>
           <execution>
             <id>generate-tests-sources</id>
             ...
             <configuration>
               <target>
                 <qtestgen ... />
                 <qtestgen ... />
               </target>
             </configuration>
           </execution>
         </executions>
       </plugin>
     </plugins>
    </build>
    '''

    plugins = pomtree.getroot() \
        .find("%sbuild" % PREFIX_XMLNS) \
        .find("%splugins" % PREFIX_XMLNS)

    for plugin in plugins.findall("%splugin" % PREFIX_XMLNS):
        if plugin.find("%sgroupId" % PREFIX_XMLNS).text == "org.apache.maven.plugins":
            executions = plugin.find("%sexecutions" % PREFIX_XMLNS)
            for execution in executions.iter("%sexecution" % PREFIX_XMLNS):
                if execution.find("%sid" % PREFIX_XMLNS).text == "generate-tests-sources":
                    target = execution.find("%sconfiguration" % PREFIX_XMLNS) \
                        .find("%starget" % PREFIX_XMLNS)

                    return target.findall("%sqtestgen" % PREFIX_XMLNS)

    return None

# Check if a qfile is included in the <qtestgen> tag by looking into the following
# attributes:
#   includeQueryFile=    List of .q files that are run if the driver is executed without using -Dqfile=
#   excludeQueryFile=    List of .q files that should be excluded from the driver
#   queryFile=           List of .q files that are executed by the driver
def is_qfile_include(qtestgen, qfile, testproperties):

    '''
    Example of a <qtestgen ... /> XML tag

    <qtestgen  ...
               queryDirectory="${basedir}/${hive.path.to.root}/ql/src/test/queries/clientpositive/"
               queryFile="${qfile}"
               excludeQueryFile="${minimr.query.files},${minitez.query.files},${encrypted.query.files}"
               includeQueryFile=""
               ...
               resultsDirectory="${basedir}/${hive.path.to.root}/ql/src/test/results/clientpositive/" className="TestCliDriver"
    ... />
    '''

    testproperties["qfile"] = qfile

    # Checks if the qfile is not excluded from qtestgen
    if qtestgen.get("excludeQueryFile") is not None:
        excludedFiles = replace_vars(qtestgen.get("excludeQueryFile"), testproperties)
        if re.compile(qfile).search(excludedFiles) is not None:
            return False

    # If includeQueryFile exists, then check if the qfile is included, otherwise return False
    if qtestgen.get("includeQueryFile") is not None:
        includedFiles = replace_vars(qtestgen.get("includeQueryFile"), testproperties)
        return re.compile(qfile).search(includedFiles) is not None

    # There are some drivers that has queryFile set to a file.
    # i.e. queryFile="hbase_bulk.m"
    # If it is set like the above line, then we should not use such driver if qfile is different
    if qtestgen.get("queryFile") is not None:
        queryFile = replace_vars(qtestgen.get("queryFile"), testproperties)
        return re.compile(qfile).search(queryFile) is not None

    return True

# Search for drivers that can run the specified qfile (.q) by looking into the 'queryDirectory' attribute
def get_drivers_for_qfile(pomtree, testproperties, qdir, qfile):
    drivers = []

    for qtestgen in find_qtestgen(pomtree):
        # Search for the <qtestgen> that matches the desired 'queryDirectory'
        if re.compile(qdir).search(qtestgen.get("queryDirectory")) is not None:
            if is_qfile_include(qtestgen, qfile, testproperties):
                drivers.append(qtestgen.get("className"))

    return drivers

# Search for drivers that can run the specified qfile result (.q.out) by looking into the 'resultsDirectory' attribute
def get_drivers_for_qresults(pomtree, testproperties, qresults, qfile):
    drivers = []

    for qtestgen in find_qtestgen(pomtree):
        if qtestgen.get("resultsDirectory"):
            # Search for the <qtestgen> that matches the desired 'resultsDirectory'
            if re.compile(qresults).search(qtestgen.get("resultsDirectory")) is not None:
                if is_qfile_include(qtestgen, qfile, testproperties):
                    drivers.append(qtestgen.get("className"))

    return drivers

#
# This command accepts a list of paths (.q or .q.out paths), and displays the
# Test drivers that should be used for testing such q-test files.
#
# The command needs the path to itests/qtest/pom.xml to look for the drivers.
#
if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths")
    parser.add_argument("--pom")
    parser.add_argument("--properties")
    args = parser.parse_args()

    if args.pom is None:
        print "The parameter '--pom' was not found."
        print "Please specify the pom.xml path by using '--pom <pom-file>'"
        sys.exit(1)

    if args.properties is None:
        print "The parameter '--properties' was not found."
        print "Please specify the testconfiguration.properties by using '--propeties <file>"
        sys.exit(1)

    if args.paths is None:
        print "The parameter '--paths' was not found"
        print "Please specify a list of comma separated .q paths (or .q.out paths)"
        sys.exit(1)

    pomtree = ET.parse(args.pom)
    testproperties = load_properties(args.properties)

    # Get all paths information, and get the correct Test driver
    if args.paths:
        tests = {}

        # --paths has a list of paths comma separated
        for p in args.paths.split(","):
            dirname = os.path.dirname(p)
            basename = os.path.basename(p)

            # Use a different method to look for .q.out files
            if re.compile("results").search(dirname):
                qfile = basename[0:basename.index(".out")]
                drivers = get_drivers_for_qresults(pomtree, testproperties, dirname, qfile)
            else:
                qfile = basename
                drivers = get_drivers_for_qfile(pomtree, testproperties, dirname, qfile)

            # We make sure to not repeat tests if for some reason we passed something
            # like a.q and a.q.out
            for d in drivers:
                if d in tests:
                    if not qfile in tests[d]:
                        tests[d].append(qfile)
                else:
                    tests[d] = [qfile]

        for t in tests:
            print "%s:%s" % (t, ",".join(tests[t]))