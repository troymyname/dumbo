import sys,types,os,random,re,types,subprocess,urllib
from itertools import groupby
from operator import itemgetter

class Job:
    def __init__(self): self.iters = []
    def additer(self,*args,**kwargs): self.iters.append((args,kwargs))
    def run(self):
        scratch = "dumbo-tmp-%i" % random.randint(0,sys.maxint)
        for index,(args,kwargs) in enumerate(self.iters):
            newopts = {"name": "%s (%s/%s)" % (sys.argv[0].split("/")[-1],
                                               index+1,len(self.iters))}
            if index != 0: 
                newopts["input"] = "%s-%i" % (scratch,index-1)
                newopts["delinputs"] = "yes"
                newopts["inputformat"] = "sequencefile"
            if index != len(self.iters)-1:
                newopts["output"] = "%s-%i" % (scratch,index)
                newopts["outputformat"] = "sequencefile"
            kwargs["iter"],kwargs["newopts"] = index,newopts
            run(*args,**kwargs)

class Program:
    def __init__(self,prog,opts=[]):
        self.prog,self.opts = prog,opts
    def addopt(self,key,value): self.opts.append((key,value))
    def delopt(self,key): return getopts(self.opts,[key],delete=True)[key]
    def getopt(self,key): return getopts(self.opts,[key],delete=False)[key]
    def start(self): return start(self.prog,self.opts)

class Counter:
    def __init__(self,name,group="Program"):
        self.group = group
        self.name = name
    def incr(self,amount):
        incrcounter(self.group,self.name,amount)

class Iteration:
    def __init__(self,prog,opts):
        self.prog,self.opts = prog,opts
        self.opts += configopts("common",prog,self.opts)
    def run(self):
        addedopts = getopts(self.opts,["fake","debug","python",
                                       "iteration","hadoop","starter"])
        if addedopts["fake"] and addedopts["fake"][0] == "yes":
            def dummysystem(*args,**kwargs): return 0
            global system
            system = dummysystem  # not very clean, but it works...
        if addedopts["debug"] and addedopts["debug"][0] == "yes":
            self.opts.append(("cmdenv","debug=yes"))
        if not addedopts["python"]: python = "python"
        else: python = addedopts["python"][0]
        self.opts.append(("python",python))
        if not addedopts["iteration"]: iter = 0
        else: iter = int(addedopts["iteration"][0])
        if not addedopts["hadoop"]: progincmd = self.prog
        else:
            self.opts.append(("hadoop",addedopts["hadoop"][0]))
            progincmd = self.prog.split("/")[-1]
        self.opts.append(("mapper","%s %s map %i" % (python,progincmd,iter)))
        self.opts.append(("reducer","%s %s red %i" % (python,progincmd,iter)))
        return 0
   
class UnixIteration(Iteration):
    def __init__(self,prog,opts):
        Iteration.__init__(self,prog,opts)
        self.opts += configopts("unix",prog,self.opts)
    def run(self):
        retval = Iteration.run(self)
        if retval != 0: return retval
        addedopts = getopts(self.opts,["input","output","mapper","reducer",
                                       "libegg","delinputs","cmdenv","pv",
                                       "addpath","inputformat","outputformat",
                                       "numreducetasks","python"])
        mapper,reducer = addedopts["mapper"][0],addedopts["reducer"][0]
        if (not addedopts["input"]) or (not addedopts["output"]):
            print >>sys.stderr,"ERROR: input or output not specified"
            return 1
        inputs = addedopts["input"]
        output = addedopts["output"][0]
        pyenv = envdef("PYTHONPATH",addedopts["libegg"],
                       shortcuts=dict(configopts("eggs",self.prog)))
        cmdenv = " ".join("%s='%s'" % tuple(arg.split("=")) \
                          for arg in addedopts["cmdenv"])
        if addedopts["pv"] and addedopts["pv"][0] == "yes":
            mpv = "| pv -s `du -b %s | cut -f 1` -cN map " % " ".join(inputs)
            spv,rpv = "| pv -cN sort ","| pv -cN reduce "
        else: mpv,spv,rpv = "","",""
        python = addedopts["python"][0]
        encodepipe = python + " -m dumbo encodepipe -file " + " -file ".join(inputs)
        if addedopts["inputformat"] and addedopts["inputformat"][0] != "text":
            encodepipe += " -alreadycoded yes"
        if addedopts["addpath"] and addedopts["addpath"][0] == 'yes':
            encodepipe += " -addpath yes"
        if addedopts["numreducetasks"] and addedopts["numreducetasks"][0] == "0":
            retval = execute("%s | %s %s %s %s > '%s'" % \
                             (encodepipe,pyenv,cmdenv,mapper,mpv,output))
        else:
            retval = execute("%s | %s %s %s %s| LC_ALL=C " \
                             "sort %s| %s %s %s %s> '%s'" % \
                             (encodepipe,pyenv,cmdenv,mapper,mpv,
                              spv,pyenv,cmdenv,reducer,rpv,output))
        if addedopts["delinputs"] and addedopts["delinputs"][0] == "yes":
            for file in addedopts["input"]: execute("rm " + file)
        return retval

class StreamingIteration(Iteration):
    def __init__(self,prog,opts):
        Iteration.__init__(self,prog,opts)
        self.opts += configopts("streaming",prog,self.opts)
    def run(self):
        retval = Iteration.run(self)
        if retval != 0: return retval
        self.opts.append(("file",self.prog))
        self.opts.append(("file",sys.argv[0]))
        addedopts = getopts(self.opts,["hadoop","name","delinputs","libegg",
                                       "libjar","inputformat","outputformat",
                                       "nummaptasks","numreducetasks","priority",
                                       "cachefile","cachearchive","codewritable",
                                       "addpath","python"])
        hadoop = findhadoop(addedopts["hadoop"][0])
        streamingjar,dumbojar = findjar(hadoop,"streaming"),findjar(hadoop,"dumbo")
        if not streamingjar:
            print >>sys.stderr,"ERROR: Streaming jar not found"
            return 1
        if not dumbojar:
            print >>sys.stderr,"ERROR: Dumbo jar not found"
            return 1
        addedopts["libjar"].append(dumbojar)
        dumbopkg = "org.apache.hadoop.dumbo"
        if not addedopts["name"]:
            self.opts.append(("jobconf","mapred.job.name=" + self.prog.split("/")[-1]))
        else: self.opts.append(("jobconf","mapred.job.name=%s" % addedopts["name"][0]))
        if addedopts["nummaptasks"]:
            self.opts.append(("jobconf",
                              "mapred.map.tasks=%s" % addedopts["nummaptasks"][0]))
        if addedopts["numreducetasks"]: 
            numreducetasks = int(addedopts["numreducetasks"][0])
            self.opts.append(("numReduceTasks",str(numreducetasks)))
            if numreducetasks == 0:
                self.opts.append(("jobconf",
                                  "mapred.mapoutput.key.class=%s.CodeWritable" % dumbopkg))
                self.opts.append(("jobconf",
                                  "mapred.mapoutput.value.class=%s.CodeWritable" % dumbopkg))
                addedopts["codewritable"] = ['no']
        if addedopts["priority"]:
            self.opts.append(("jobconf",
                              "mapred.job.priority=%s" % addedopts["priority"][0]))
        if addedopts["cachefile"]: self.opts.append(("cacheFile",
                                                     addedopts["cachefile"][0]))
        if addedopts["cachearchive"]: self.opts.append(("cacheArchive",
                                                        addedopts["cachearchive"][0]))
        if not addedopts["inputformat"]: addedopts["inputformat"] = ["sequencefile"] 
        inputformat_shortcuts = {
            "text": dumbopkg + ".TextAsCodeInputFormat", 
            "sequencefile": dumbopkg + ".SequenceFileAsCodeInputFormat",
            "auto": dumbopkg + ".AutoAsCodeInputFormat"}
        inputformat_shortcuts.update(configopts("inputformats",self.prog))
        inputformat = addedopts["inputformat"][0]
        if inputformat_shortcuts.has_key(inputformat.lower()):
            inputformat = inputformat_shortcuts[inputformat.lower()]
        if inputformat.endswith("AsCodeInputFormat"):
            self.opts.append(("inputformat",inputformat))
        else:
            self.opts.append(("jobconf","dumbo.as.code.input.format.class=" + inputformat))
            self.opts.append(("inputformat",dumbopkg + ".AsCodeInputFormat"))
        if not addedopts["outputformat"]: addedopts["outputformat"] = ["sequencefile"] 
        outputformat_shortcuts = {
            "sequencefile": "org.apache.hadoop.mapred.SequenceFileOutputFormat"}
        outputformat_shortcuts.update(configopts("outputformats",self.prog))
        outputformat = addedopts["outputformat"][0]
        if outputformat_shortcuts.has_key(outputformat.lower()):
            outputformat = outputformat_shortcuts[outputformat.lower()]
        self.opts.append(("jobconf","dumbo.from.code.output.format.class=" + outputformat))
        self.opts.append(("outputformat",dumbopkg + ".FromCodeOutputFormat"))
        if not (addedopts["codewritable"] and addedopts["codewritable"][0] == 'no'):
            self.opts.append(("jobconf",
                              "mapred.mapoutput.key.class=%s.CodeWritable" % dumbopkg))
            self.opts.append(("jobconf",
                              "mapred.mapoutput.value.class=%s.CodeWritable" % dumbopkg))
            opt = getopts(self.opts,["mapper"])["mapper"]
            self.opts.append(("jobconf","stream.map.streamprocessor=" + \
                              urllib.quote_plus(opt[0])))
            self.opts.append(("mapper",dumbopkg + ".CodeWritableMapper"))
            self.opts.append(("jobconf","dumbo.code.writable.map.class=" \
                              "org.apache.hadoop.streaming.PipeMapper"))
        if addedopts["addpath"] and addedopts["addpath"][0] == 'yes':
            self.opts.append(("jobconf", "dumbo.as.named.code=true"))
        envdef("PYTHONPATH",addedopts["libegg"],"file",self.opts,
               shortcuts=dict(configopts("eggs",self.prog)))
        hadenv = envdef("HADOOP_CLASSPATH",addedopts["libjar"],"file",self.opts,
                        shortcuts=dict(configopts("jars",self.prog))) 
        cmd = hadoop + "/bin/hadoop jar " + streamingjar
        retval = execute(cmd,self.opts,hadenv)
        if addedopts["delinputs"] and addedopts["delinputs"][0] == "yes":
            for key,value in self.opts:
                if key == "input":
                    execute("%s/bin/hadoop dfs -rmr '%s'" % (hadoop,value))
        return retval
        

def main(runner,starter=None):
    opts = parseargs(sys.argv[1:])
    starteropt = getopts(opts,["starter"])["starter"]
    opts.append(("starter","no"))
    if starter and not (starteropt and starteropt[0] == 'no') and \
       not (len(sys.argv) > 1 and sys.argv[1][0] != "-"):
        program = Program(sys.argv[0],opts)
        errormsg = starter(program)
        if errormsg:
            print >>sys.stderr,errormsg
            sys.exit(1)
        program.start()
    else:
        job = Job()
        errormsg = runner(job)
        if errormsg:
            print >>sys.sdterr,errormsg
            sys.exit(1)
        job.run()

def run(mapper,reducer=None,combiner=None,
        mapconf=None,redconf=None,mapclose=None,redclose=None,
        iter=0,newopts={}):
    if len(sys.argv) > 1 and not sys.argv[1][0] == "-":
        try:
            regex = re.compile(".*\.egg")
            for eggfile in filter(regex.match,os.listdir(".")):
                sys.path.append(eggfile)  # add eggs in current dir to path
        except: pass
        if type(mapper) == types.ClassType:
            if hasattr(mapper,'map'): mapper = mapper().map
            else: mapper = mapper()
        if type(reducer) == types.ClassType:
            if hasattr(reducer,'reduce'): reducer = reducer().reduce
            else: reducer = reducer()
        if type(combiner) == types.ClassType:
            if hasattr(combiner,'reduce'): combiner = combiner().reduce
            else: combiner = combiner()
        iterarg = 0  # default value
        if len(sys.argv) > 2: iterarg = int(sys.argv[2])
        if iterarg == iter:
            inputs = loadcode(line[:-1] for line in sys.stdin)
            if sys.argv[1].startswith("map"):
                if mapconf: mapconf()
                outputs = itermap(inputs,mapper)
                if combiner: outputs = iterreduce(sorted(outputs),combiner)
                if mapclose: mapclose()
            elif reducer: 
                if redconf: redconf()
                outputs = iterreduce(inputs,reducer)
                if redclose: redclose()
            else: outputs = inputs
            for output in dumpcode(outputs): print "\t".join(output)
    else:
        opts = parseargs(sys.argv[1:])
        newopts["iteration"] = str(iter)
        if not reducer: newopts["numreducetasks"] = "0"
        key,delindexes = None,[]
        for index,(key,value) in enumerate(opts):
            if newopts.has_key(key): delindexes.append(index)
        for delindex in reversed(delindexes): del opts[delindex]
        opts += newopts.iteritems()
        hadoopopt = getopts(opts,["hadoop"],delete=False)["hadoop"]
        if hadoopopt: retval = StreamingIteration(sys.argv[0],opts).run()
        else: retval = UnixIteration(sys.argv[0],opts).run()
        if retval == 127:
            print >>sys.stderr,'ERROR: Are you sure that "python" is on your path?'
        if retval != 0: sys.exit(retval)

def identitymapper(key,value):
    yield key,value

def identityreducer(key,values):
    for value in values: yield key,value
    
def sumreducer(key,values):
    yield key,sum(values)

def incrcounter(group,counter,amount):
    print >>sys.stderr,"reporter:counter:%s,%s,%s" % (group,counter,amount)

def setstatus(message):
    print >>sys.stderr,"reporter:status:%s" % message
    
def itermap(data,mapfunc):
    for key,value in data: 
        for output in mapfunc(key,value): yield output

def iterreduce(data,redfunc):
    for key,values in groupby(data,itemgetter(0)):
        for output in redfunc(key,(v[1] for v in values)): yield output

def itermapred(data,mapfunc,redfunc):
    return iterreduce(sorted(itermap(data,mapfunc)),redfunc)

def dumpcode(outputs):
    for output in outputs: yield map(repr,output)

def loadcode(inputs):
    for input in inputs:
        try: yield map(eval,input.split("\t",1))
        except:
            if os.environ.has_key("debug"): raise
            print >>sys.stderr,"WARNING: skipping bad input (%s)" % input
            incrcounter("Dumbo","Bad inputs",1)

def dumptext(outputs):
    newoutput = []
    for output in outputs:
        for item in output:
            if not hasattr(item,"__iter__"): newoutput.append(str(item))
            else: newoutput.append("\t".join(map(str,item)))
        yield newoutput
        del newoutput[:]

def loadtext(inputs):
    offset = 0
    for input in inputs: 
        yield (offset,input)
        offset += len(input)    

def parseargs(args):
    opts,key,values = [],None,[]
    for arg in args:
        if arg[0] == "-" and len(arg) > 1:
            if key: opts.append((key," ".join(values)))
            key,values = arg[1:],[]
        else: values.append(arg)
    if key: opts.append((key," ".join(values)))
    return opts

def getopts(opts,keys,delete=True):
    askedopts = dict((key,[]) for key in keys)
    key,delindexes = None,[]
    for index,(key,value) in enumerate(opts):
        key = key.lower()
        if askedopts.has_key(key):
            askedopts[key].append(value)
            delindexes.append(index)
    if delete:
        for delindex in reversed(delindexes): del opts[delindex]
    return askedopts

def configopts(section,prog=None,opts=[]):
    from ConfigParser import SafeConfigParser,NoSectionError
    if prog: defaults = {'prog': prog.split("/")[-1].split(".py",1)[0]}
    else: defaults = {}
    try: defaults.update([('user',os.environ["USER"]),('pwd',os.environ["PWD"])])
    except KeyError: pass
    for key,value in opts: defaults[key] = value
    parser = SafeConfigParser(defaults)
    parser.read(["/etc/dumbo.conf",os.environ["HOME"]+"/.dumborc"])
    results,excludes = [],set(defaults.iterkeys())
    try: 
        for key,value in parser.items(section):
            if not key in excludes: 
                results.append((key.split("_",1)[0],value))
    except NoSectionError: pass
    return results

def execute(cmd,opts=[],precmd="",printcmd=True,stdout=sys.stdout,stderr=sys.stderr):
    if precmd: cmd = " ".join((precmd,cmd))
    args = " ".join("-%s '%s'" % (key,value) for key,value in opts)
    if args: cmd = " ".join((cmd,args))
    if printcmd: print >>stderr,"EXEC:",cmd
    return system(cmd,stdout,stderr)
    
def system(cmd,stdout=sys.stdout,stderr=sys.stderr):
    if sys.version[:3] == "2.4": return os.system(cmd) / 256
    proc = subprocess.Popen(cmd,shell=True,stdout=stdout,stderr=stderr)
    return os.waitpid(proc.pid,0)[1] / 256

def findhadoop(optval):
    hadoop,hadoop_shortcuts = optval,dict(configopts("hadoops"))
    if hadoop_shortcuts.has_key(hadoop.lower()):
        hadoop = hadoop_shortcuts[hadoop.lower()]
    if not os.path.exists(hadoop):
        print >>sys.stderr,"ERROR: directory %s does not exist" % hadoop
        sys.exit(1)
    return hadoop

def findjar(hadoop,name):
    jardir = hadoop + "/build/contrib/" + name
    if not os.path.exists(jardir): jardir = hadoop + "/contrib/" + name
    if not os.path.exists(jardir): jardir = hadoop + "/contrib"
    regex = re.compile("hadoop.*" + name + "\.jar")
    try: return jardir + "/" + filter(regex.match,os.listdir(jardir))[-1]
    except: return None

def envdef(varname,files,optname=None,opts=None,commasep=False,shortcuts={}):
    path,optvals="",[]
    for file in files:
        if shortcuts.has_key(file.lower()): file = shortcuts[file.lower()]
        path += file + ":"
        optvals.append(file)
    if optname and optvals:
        if not commasep: 
            for optval in optvals: opts.append((optname,optval))
        else: opts.append((optname,",".join(optvals)))
    return '%s="%s$%s"' % (varname,path,varname)


def start(prog,opts,stdout=sys.stdout,stderr=sys.stderr):
    addedopts = getopts(opts,["libegg"],delete=False)
    pyenv = envdef("PYTHONPATH",addedopts["libegg"],
                   shortcuts=dict(configopts("eggs",prog)))
    return execute("python '%s'" % prog,opts,pyenv,
                   stdout=stdout,stderr=stderr,printcmd=False)

def submit(*args,**kwargs):
    print >>sys.stderr,"WARNING: submit() is deprecated, use start() instead"
    return start(*args,**kwargs)

def cat(path,opts):
    addedopts = getopts(opts,["hadoop","type","libjar"])
    if not addedopts["hadoop"]: return decodepipe(opts + [("file",path)])
    hadoop = findhadoop(addedopts["hadoop"][0])
    dumbojar = findjar(hadoop,"dumbo")
    if not dumbojar:
        print >>sys.stderr,"ERROR: Dumbo jar not found"
        return 1
    if not addedopts["type"]: type = "auto"
    else: type = addedopts["type"][0]
    hadenv = envdef("HADOOP_CLASSPATH",addedopts["libjar"],
                    shortcuts=dict(configopts("jars")))
    try:
        if type[:4] == "auto": codetype = "autoascode"
        elif type[:4] == "text": codetype = "textascode"
        else: codetype = "sequencefileascode"
        process = os.popen("%s %s/bin/hadoop jar %s catpath %s %s" % \
            (hadenv,hadoop,dumbojar,codetype,path))    
        if type[-6:] == "ascode": outputs = dumpcode(loadcode(process))
        else: outputs = dumptext(loadcode(process))
        for output in outputs: print "\t".join(output)
        process.close()
    except IOError: pass  # ignore
    return 0

def encodepipe(opts=[]):
    addedopts = getopts(opts,["addpath","file","alreadycoded"])
    if addedopts["file"]: files = (open(f) for f in addedopts["file"])
    else: files = [sys.stdin]
    for file in files:
        outputs = (line[:-1] for line in file)
        if addedopts["alreadycoded"]: outputs = loadcode(outputs)
        else: outputs = loadtext(outputs)
        if addedopts["addpath"]: 
            outputs = (((file.name,key),value) for key,value in outputs)
        for output in dumpcode(outputs): print "\t".join(output)
        file.close()
    return 0
    
def decodepipe(opts=[]):
    addedopts = getopts(opts,["file"])
    if addedopts["file"]: files = (open(f) for f in addedopts["file"])
    else: files = [sys.stdin]
    for file in files:
        outputs = loadcode(line[:-1] for line in file)
        for output in dumptext(outputs): print "\t".join(output)
        file.close()
        return 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print "Usages:"
        print "  python -m dumbo start <python program> [<options>]"
        print "  python -m dumbo cat <path> [<options>]"
        print "  python -m dumbo encodepipe [<options>]"
        print "  python -m dumbo decodepipe [<options>]"
        sys.exit(1)
    if sys.argv[1] == "start":
        retval = start(sys.argv[2],parseargs(sys.argv[2:]))
    elif sys.argv[1] == "submit":
        retval = submit(sys.argv[2],parseargs(sys.argv[2:]))
    elif sys.argv[1] == "cat":
        retval = cat(sys.argv[2],parseargs(sys.argv[2:]))
    elif sys.argv[1] == "encodepipe":
        retval = encodepipe(parseargs(sys.argv[2:]))
    elif sys.argv[1] == "decodepipe":
        retval = decodepipe(parseargs(sys.argv[2:]))
    else:
        retval = start(sys.argv[1],parseargs(sys.argv[1:]))
    sys.exit(retval)