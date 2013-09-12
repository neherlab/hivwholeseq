#!/usr/bin/env python
# vim: fdm=marker
'''
author:     Fabio Zanini
date:       26/08/13
content:    Build a subset of the mapped reads excluding mismappings.
'''
# Modules
import os
import sys
import argparse
import cPickle as pickle
from collections import defaultdict
from itertools import izip
import pysam
import numpy as np
from Bio import SeqIO


# Horizontal import of modules from this folder
from mapping.adapter_info import load_adapter_table, foldername_adapter
from mapping.miseq import alpha, read_types
from mapping.filenames import get_consensus_filename, get_mapped_filename
from mapping.mapping_utils import get_ind_good_cigars, convert_sam_to_bam,\
        pair_generator



# Globals
VERBOSE = 1

# FIXME
from mapping.datasets import dataset_testmiseq as dataset
data_folder = dataset['folder']

maxreads = 1e9
match_len_min = 30
trim_bad_cigars = 3

# Cluster submit
import mapping
JOBDIR = mapping.__path__[0].rstrip('/')+'/'
JOBLOGERR = JOBDIR+'logerr'
JOBLOGOUT = JOBDIR+'logout'
JOBSCRIPT = JOBDIR+'filter_mapped_reads.py'
cluster_time = '0:59:59'
vmem = '8G'



# Functions
def fork_self(data_folder, adaID, fragment, VERBOSE=0):
    '''Fork self for each adapter ID'''
    import subprocess as sp

    qsub_list = ['qsub','-cwd',
                 '-b', 'y',
                 '-S', '/bin/bash',
                 '-o', JOBLOGOUT,
                 '-e', JOBLOGERR,
                 '-N', 'fmr '+'{:02d}'.format(adaID),
                 '-l', 'h_rt='+cluster_time,
                 '-l', 'h_vmem='+vmem,
                 JOBSCRIPT,
                 '--adaIDs', adaID,
                 '--fragments', fragment,
                 '--verbose', VERBOSE,
                ]
    qsub_list = map(str, qsub_list)
    if VERBOSE:
        print ' '.join(qsub_list)
    sp.call(qsub_list)


def filter_reads(data_folder, adaID, fragment, VERBOSE=0):
    '''Filter the reads to good chunks'''

    # Read reference (fragmented)
    reffilename = get_consensus_filename(data_folder, adaID, fragment)
    refseq = SeqIO.read(reffilename, 'fasta')
    ref = np.array(refseq)

    # Get BAM files
    bamfilename = get_mapped_filename(data_folder, adaID, fragment, type='bam')
    # Try to convert to BAM if needed
    if not os.path.isfile(bamfilename):
        convert_sam_to_bam(bamfilename)

    outfilename = get_mapped_filename(data_folder, adaID, fragment, type='bam',
                                     filtered=True)
    trashfilename = outfilename[:-4]+'_trashed.bam'
 
    with pysam.Samfile(bamfilename, 'rb') as bamfile:
        with pysam.Samfile(outfilename, 'wb', template=bamfile) as outfile,\
             pysam.Samfile(trashfilename, 'wb', template=bamfile) as trashfile:
 
            # Iterate over all pairs
            n_good = 0
            n_unmapped = 0
            n_unpaired = 0
            n_mismapped_edge = 0
            for i_pairs, reads in enumerate(pair_generator(bamfile)):
            
                # Limit to the first reads
                if 2 * i_pairs >= maxreads: break
            
                # Assign names
                (read1, read2) = reads

                # Flag to decide on the read
                skip = False
            
                # Check a few things to make sure we are looking at paired reads
                if read1.qname != read2.qname:
                    raise ValueError('Read pair '+str(i_pairs)+': reads have different names!')
                # Ignore unmapped reads
                elif read1.is_unmapped or read2.is_unmapped:
                    if VERBOSE >= 2:
                        print 'Read pair '+read1.qname+': unmapped'
                    n_unmapped += 1
                    skip = True
            
                # Ignore not properly paired reads (this includes mates sitting on
                # different fragments)
                elif (not read1.is_proper_pair) or (not read2.is_proper_pair):
                    if VERBOSE >= 2:
                        print 'Read pair '+read1.qname+': not properly paired'
                    n_unpaired += 1
                    skip = True

                else:
            
                    # Mismappings are often characterized by a large number of mutations,
                    # and/or an overhang before the beginning of the fragment or beyond 
                    # its end
                    muts = []
                    for read in reads:
            
                        # Check overhangs
                        read_start = read.pos
                        read_end = read.pos + sum(x[1] for x in read.cigar if x[0] != 1)
                        if (((read_start == 0) and (read.cigar[0][0] == 1)) or
                            ((read_end == len(ref)) and (read.cigar[-1][0] == 1))):
                            n_mismapped_edge += 1
                            skip = True
                            break

                # Write the output
                if not skip:
                    n_good += 1
                    map(outfile.write, reads)
                else:
                    map(trashfile.write, reads)

    if VERBOSE >= 3:
        print 'Reads: '+str(n_good)+' good, '+str(n_unmapped)+' unmapped, '+\
                str(n_unpaired)+' unpaired, '+str(n_mismapped_edge)+' edge.'



# Script
if __name__ == '__main__':

    # Input arguments
    parser = argparse.ArgumentParser(description='Extract linkage information')
    parser.add_argument('--adaIDs', nargs='*', type=int,
                        help='Adapter IDs to analyze (e.g. 2 16)')
    parser.add_argument('--fragments', nargs='*',
                        help='Fragment to map (e.g. F1 F6)')
    parser.add_argument('--verbose', type=int, default=0,
                        help=('Verbosity level [0-3]'))
    parser.add_argument('--submit', action='store_true', default=False,
                        help='Submit the job to the cluster via qsub')
    args = parser.parse_args()
    adaIDs = args.adaIDs
    fragments = args.fragments
    VERBOSE = args.verbose
    submit = args.submit

    # If the script is called with no adaID, iterate over all
    if not adaIDs:
        adaIDs = load_adapter_table(data_folder)['ID']
    if VERBOSE >= 3:
        print 'adaIDs', adaIDs

    # If the script is called with no fragment, iterate over all
    if not fragments:
        fragments = ['F'+str(i) for i in xrange(1, 7)]
    if VERBOSE >= 3:
        print 'fragments', fragments

    # Iterate over all requested samples
    for fragment in fragments:
        for adaID in adaIDs:

            # Submit to the cluster self if requested
            if submit:
                fork_self(data_folder, adaID, fragment, VERBOSE=VERBOSE)
                continue

            # or else, perform the filtering
            filter_reads(data_folder, adaID, fragment, VERBOSE=VERBOSE)
