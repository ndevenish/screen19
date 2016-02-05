from __future__ import division
from logging import info, debug, warn
import json
import math
import os
import re
import sys

from i19.util.procrunner import run_process

help_message = '''
This program processes screening data obtained at Diamond Light Source
Beamline I19-1.

Examples:

  i19.screen datablock.json

  i19.screen *.cbf

  i19.screen /path/to/data/

'''

class i19_screen():
  import libtbx.load_env

  def _prettyprint_dictionary(self, d):
    return "{\n%s\n}" % \
      "\n".join(["  %s: %s" % (k, str(d[k]).replace("\n", "\n%s" % (" " * (4 + len(k)))))
        for k in d.iterkeys() ])

  def _import(self, files):
    info("\nImporting data...")
    command = [ "dials.import" ] + files
    debug("running %s" % " ".join(command))

    result = run_process(command, print_stdout=False)
    debug("result = %s" % self._prettyprint_dictionary(result))

    if result['exitcode'] == 0:
      if os.path.isfile('datablock.json'):
        info("Successfully completed (%.1f sec)" % result['runtime'])
      else:
        warn("Could not import images. Do the specified images exist at that location?")
        sys.exit(1)
    else:
      warn("Failed with exit code %d" % result['exitcode'])
      sys.exit(1)

  def _count_processors(self):
    command = [ "libtbx.show_number_of_processors" ]
    debug("running %s" % command)
    result = run_process(command, print_stdout=False)
    debug("result = %s" % self._prettyprint_dictionary(result))
    if result['exitcode'] == 0:
      self.nproc = result['stdout']
    else:
      warn("Could not determine number of available processors. Error code %d" % result['exitcode'])
      sys.exit(1)

  def _check_intensities(self):
    info("\nTesting pixel intensities...")
    command = [ "xia2.overload", self.json_file ]
    result = run_process(command, print_stdout=False)
    debug("result = %s" % self._prettyprint_dictionary(result))

    if result['exitcode'] != 0:
      warn("Failed with exit code %d" % result['exitcode'])
      sys.exit(1)

    with open('overload.json') as fh:
      overload_data = json.load(fh)

    print "Pixel intensity distribution:"
    count_sum = 0
    hist = {}
    for b in range(overload_data['bin_count']):
      if overload_data['bins'][b] > 0:
        hist[b] = overload_data['bins'][b]
        count_sum += b * overload_data['bins'][b]

    histcount = sum(hist.itervalues())

    # we have checked this: if _sigma_m >> _oscillation it works out about 1
    # as you would expect
    mosaicity_factor = math.sqrt(math.pi) * self._sigma_m * \
      math.erf(self._oscillation / (2 * self._sigma_m))

    info("Mosaicity factor: %f" % mosaicity_factor)
    scale = 100 * overload_data['scale_factor'] / mosaicity_factor
    info("Determined scale factor for intensities as %f" % scale)
    debug("intensity histogram: { %s }", ", ".join(["%d:%d" % (k, hist[k]) for k in sorted(hist)]))
    rescaled_hist = {}
    for x in hist.iterkeys():
      rescaled = int(x * scale / 10) * 10 + 5
      rescaled = int(x * scale)
      try:
        rescaled_hist[rescaled] += hist[x]
      except Exception:
        rescaled_hist[rescaled] = hist[x]
    hist = rescaled_hist
    debug("rescaled histogram: { %s }", ", ".join(["%d:%d" % (k, hist[k]) for k in sorted(hist)]))
    del hist[0]

    self._plot_intensities(hist)

    hist_max = max(hist.iterkeys())
    text = "Strongest pixel reaches %.1f %% of the detector count rate limit" % hist_max
    if (hist_max > 100):
      warn("Warning: %s!" % text)
    else:
      info(text)

    if (histcount % self._num_images) != 0:
      warn("Warning: There may be undetected overloads above the upper bound!")

    info("Total sum of counts in dataset: %d" % count_sum)

    info("Successfully completed (%.1f sec)" % result['runtime'])

  def _plot_intensities(self, bins):
    rows, columns = 25, 80
    if sys.stdout.isatty():
      try:
        import subprocess
        rows, columns = subprocess.check_output(['stty', 'size']).split()
      except Exception:
        pass

    command = [ "gnuplot" ]
    plot_commands = [
      "set term dumb %s %d" % (columns, int(rows)-2),
      "set title 'Spot intensity distribution'",
      "set xlabel '% of maximum'",
      "set ylabel 'Number of observed pixels'",
      "set logscale y",
      "set boxwidth 1.0",
      "set xtics out nomirror",
      "set ytics out",
      "plot '-' using 1:2 title '' with boxes"
    ]
    for x in sorted(bins.iterkeys()):
      plot_commands.append("%f %d" % (x, bins[x]))
    plot_commands.append("e")

    debug("running %s with:\n  %s\n" % (" ".join(command), "\n  ".join(plot_commands)))

    result = run_process(command, stdin="\n".join(plot_commands)+"\n", timeout=120, print_stdout=False)

    debug("result = %s" % self._prettyprint_dictionary(result))

    if result['exitcode'] == 0:
      star = re.compile(r'\*')
      space = re.compile(' ')
      state = set()
      for l in result['stdout'].split("\n"):
        if l.strip() != '':
          stars = {m.start(0) for m in re.finditer(star, l)}
          if len(stars) == 0:
            state = set()
          else:
            state |= stars
            l = list(l)
            for s in state: l[s] = '*'
          info("".join(l))
    else:
      warn("Error running gnuplot. Can not plot intensity distribution. Exit code %d" % result['exitcode'])

  def _find_spots(self, additional_parameters=[]):
    info("\nSpot finding...")
    command = [ "dials.find_spots", self.json_file, "nproc=%s" % self.nproc ] + additional_parameters
    result = run_process(command, print_stdout=False)
    debug("result = %s" % self._prettyprint_dictionary(result))
    if result['exitcode'] != 0:
      warn("Failed with exit code %d" % result['exitcode'])
      sys.exit(1)
    info(60 * '-')
    from libtbx import easy_pickle
    from dials.util.ascii_art import spot_counts_per_image_plot
    refl = easy_pickle.load('strong.pickle')
    info(spot_counts_per_image_plot(refl))
    info(60 * '-')
    info("Successfully completed (%.1f sec)" % result['runtime'])


  def _index(self):
    base_command = [ "dials.index", self.json_file, "strong.pickle", "indexing.nproc=%s" % self.nproc ]
    runlist = [
      ("Indexing...",
        base_command),
      ("Retrying with max_cell constraint",
        base_command + [ "max_cell=20" ]),
      ("Retrying with 1D FFT",
        base_command + [ "indexing.method=fft1d" ])
      ]

    for message, command in runlist:
      info("\n%s..." % message)

      result = run_process(command, print_stdout=False)
      debug("result = %s" % self._prettyprint_dictionary(result))
      if result['exitcode'] != 0:
        warn("Failed with exit code %d" % result['exitcode'])
      else:
        break

    if result['exitcode'] != 0:
      return False

    m = re.search('model [0-9]+ \(([0-9]+) [^\n]*\n[^\n]*\n[^\n]*Unit cell: \(([^\n]*)\)\n[^\n]*Space group: ([^\n]*)\n', result['stdout'])
    info("Found primitive solution: %s (%s) using %s reflections" % (m.group(3), m.group(2), m.group(1)))
    info("Successfully completed (%.1f sec)" % result['runtime'])
    return True

  def _refine(self):
    info("\nIndexing...")
    command = [ "dials.refine", "experiments.json", "indexed.pickle" ]
    result = run_process(command, print_stdout=False)
    debug("result = %s" % self._prettyprint_dictionary(result))
    if result['exitcode'] != 0:
      warn("Failed with exit code %d" % result['exitcode'])
      warn("Giving up.")
      sys.exit(1)

    info("Successfully refined (%.1f sec)" % result['runtime'])
    os.rename("experiments.json", "experiments.unrefined.json")
    os.rename("indexed.pickle", "indexed.unrefined.pickle")
    os.rename("refined_experiments.json", "experiments.json")
    os.rename("refined.pickle", "indexed.pickle")

  def _predict(self):
    info("\nPredicting reflections...")
    command = [ "dials.predict", "experiments_with_profile_model.json" ]
    result = run_process(command, print_stdout=False)
    debug("result = %s" % self._prettyprint_dictionary(result))
    if result['exitcode'] == 0:
      info("To view predicted reflections run:")
      info("  dials.image_viewer experiments_with_profile_model.json predicted.pickle")
      info("Successfully completed (%.1f sec)" % result['runtime'])
      return True
    else:
      warn("Failed with exit code %d" % result['exitcode'])
      return False

  def _create_profile_model(self):
    info("\nCreating profile model...")
    command = [ "dials.create_profile_model", "experiments.json", "indexed.pickle" ]
    result = run_process(command, print_stdout=False)
    debug("result = %s" % self._prettyprint_dictionary(result))
    if result['exitcode'] == 0:
      from dxtbx.model.experiment.experiment_list import ExperimentListFactory
      db = ExperimentListFactory.from_json_file('experiments_with_profile_model.json')[0]
      self._num_images = db.imageset.get_scan().get_num_images()
      self._oscillation = db.imageset.get_scan().get_oscillation()[1]
      self._sigma_m = db.profile.sigma_m()
      info("%d images, %s deg. oscillation, sigma_m=%.3f" % (self._num_images, str(self._oscillation), self._sigma_m))
      info("Successfully completed (%.1f sec)" % result['runtime'])
      return True
    else:
      warn("Failed with exit code %d" % result['exitcode'])
      return False

  def _refine_bravais(self):
    info("\nRefining bravais settings...")
    command = [ "dials.refine_bravais_settings", "experiments.json", "indexed.pickle" ]
    result = run_process(command, print_stdout=False)
    debug("result = %s" % self._prettyprint_dictionary(result))
    if result['exitcode'] == 0:
      m = re.search('---+\n[^\n]*\n---+\n(.*\n)*---+', result['stdout'])
      info(m.group(0))
      info("Successfully completed (%.1f sec)" % result['runtime'])
    else:
      warn("Failed with exit code %d" % result['exitcode'])
      sys.exit(1)

  def _report(self):
    info("\nCreating report...")
    command = [ "dials.report", "experiments_with_profile_model.json", "indexed.pickle" ]
    result = run_process(command, print_stdout=False)
    debug("result = %s" % self._prettyprint_dictionary(result))
    if result['exitcode'] == 0:
      info("Successfully completed (%.1f sec)" % result['runtime'])
#     if sys.stdout.isatty():
#       info("Trying to start browser")
#       try:
#         import subprocess
#         d = dict(os.environ)
#         d["LD_LIBRARY_PATH"] = ""
#         subprocess.Popen(["xdg-open", "dials-report.html"], env=d)
#       except Exception, e:
#         debug("Could not open browser")
#         debug(str(e))
    else:
      warn("Failed with exit code %d" % result['exitcode'])
      sys.exit(1)

  def run(self, args):
    from dials.util.version import dials_version
    from i19.util.version import i19_version
    version_information = "%s using %s" % (i19_version(), dials_version())

    if len(args) == 0:
      print help_message
      print version_information
      return

    # Configure the logging
    from dials.util import log
    log.config(1, info='i19.screen.log', debug='i19.screen.debug.log')

    info(version_information)

    self._count_processors()

    if len(args) == 1 and args[0].endswith('.json'):
      self.json_file = args[0]
    else:
      self._import(args)
      self.json_file = 'datablock.json'

    self._find_spots()
    if not self._index():
      info("\nRetrying for stronger spots only...")
      os.rename("strong.pickle", "all_spots.pickle")
      self._find_spots(['sigma_strong=15'])
      if not self._index():
        warn("Giving up.")
        info("""
Could not find an indexing solution. You may want to have a look
at the reciprocal space by running:

  dials.reciprocal_lattice_viewer datablock.json all_spots.pickle

or, to only include stronger spots:

  dials.reciprocal_lattice_viewer datablock.json strong.pickle
""")
        sys.exit(1)

    if not self._create_profile_model():
      info("\nRefining model to attempt to increase number of valid spots...")
      self._refine()
      if not self._create_profile_model():
        warn("Giving up.")
        info("""
The identified indexing solution may not be correct. You may want to have a look
at the reciprocal space by running:

  dials.reciprocal_lattice_viewer experiments.json indexed.pickle
""")
        sys.exit(1)
    self._report()
    self._predict()
    self._check_intensities()
    self._refine_bravais()

    return

if __name__ == '__main__':
  i19_screen().run(sys.argv[1:])
