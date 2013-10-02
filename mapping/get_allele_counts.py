#!/usr/bin/env python
# vim: fdm=indent
'''
author:     Fabio Zanini
date:       05/08/13
content:    Get the allele frequencies out of a BAM file and a reference.
'''
# Modules
import os
import sys
import argparse
import subprocess as sp
import cPickle as pickle
from collections import defaultdict
from itertools import izip
import pysam
import numpy as np
from Bio import SeqIO

# Horizontal import of modules from this folder
from mapping.adapter_info import load_adapter_table
from mapping.miseq import alpha, read_types
from mapping.filenames import get_mapped_filename, get_allele_counts_filename, \
        get_insert_counts_filename, get_coverage_filename, get_consensus_filename
from mapping.mapping_utils import get_ind_good_cigars, get_trims_from_good_cigars, \
        convert_sam_to_bam


# Globals
# FIXME
from mapping.datasets import dataset_testmiseq as dataset
data_folder = dataset['folder']

match_len_min = 30
trim_bad_cigars = 3

# Cluster submit
import mapping
JOBDIR = mapping.__path__[0].rstrip('/')+'/'
JOBSCRIPT = JOBDIR+'get_allele_counts.py'
JOBLOGERR = JOBDIR+'logerr'
JOBLOGOUT = JOBDIR+'logout'
# Different times based on subsample flag
cluster_time = ['23:59:59', '0:59:59']
vmem = '4G'



# Functions
def fork_self(data_folder, adaID, fragment, subsample=False, VERBOSE=3):
    '''Fork self for each adapter ID and fragment'''
    qsub_list = ['qsub','-cwd',
                 '-b', 'y',
                 '-S', '/bin/bash',
                 '-o', JOBLOGOUT,
                 '-e', JOBLOGERR,
                 '-N', 'acn '+'{:02d}'.format(adaID)+' '+fragment,
                 '-l', 'h_rt='+cluster_time[subsample],
                 '-l', 'h_vmem='+vmem,
                 JOBSCRIPT,
                 '--adaIDs', adaID,
                 '--fragments', fragment,
                 '--verbose', VERBOSE,
                ]
    if subsample:
        qsub_list.append('--subsample')
    qsub_list = map(str, qsub_list)
    if VERBOSE:
        print ' '.join(qsub_list)
    sp.call(qsub_list)


def get_allele_counts(data_folder, adaID, fragment, subsample=False, VERBOSE=0):
    '''Extract allele and insert counts from a bamfile'''

    # Read reference
    reffilename = get_consensus_filename(data_folder, adaID, fragment,
                                         subsample=subsample, trim_primers=True)
    refseq = SeqIO.read(reffilename, 'fasta')
    
    # Allele counts and inserts
    counts = np.zeros((len(read_types), len(alpha), len(refseq)), int)
    # Note: the data structure for inserts is a nested dict with:
    # position --> string --> read type --> count
    #  (dict)      (dict)       (list)      (int)
    inserts = defaultdict(lambda: defaultdict(lambda: np.zeros(len(read_types), int)))

    # Open BAM file
    # Note: the reads should already be filtered of unmapped stuff at this point
    bamfilename = get_mapped_filename(data_folder, adaID, fragment, type='bam',
                                      filtered=True)
    if not os.path.isfile(bamfilename):
        convert_sam_to_bam(bamfilename)
    with pysam.Samfile(bamfilename, 'rb') as bamfile:

        # Iterate over single reads (no linkage info needed)
        for i, read in enumerate(bamfile):
        
            # Print output
            if (VERBOSE >= 3) and (not ((i +1) % 10000)):
                print (i+1)
        
            # Divide by read 1/2 and forward/reverse
            js = 2 * read.is_read2 + read.is_reverse
        
            # Read CIGARs (they should be clean by now)
            cigar = read.cigar
            len_cig = len(cigar)
            (good_cigars, first_good_cigar, last_good_cigar) = \
                    get_ind_good_cigars(cigar, match_len_min=match_len_min,
                                        full_output=True)
            
            # Sequence and position
            # Note: stampy takes the reverse complement already
            seq = read.seq
            pos = read.pos

            # Iterate over CIGARs
            for ic, (block_type, block_len) in enumerate(cigar):

                # Check for pos: it should never exceed the length of the fragment
                if (block_type in [0, 1, 2]) and (pos > len(refseq)):
                    raise ValueError('Pos exceeded the length of the fragment')
            
                # Inline block
                if block_type == 0:
                    # Exclude bad CIGARs
                    if good_cigars[ic]: 
            
                        # The first and last good CIGARs are matches:
                        # trim them (unless they end the read)
                        if (ic == first_good_cigar) and (ic != 0):
                            trim_left = trim_bad_cigars
                        else:
                            trim_left = 0
                        if (ic == last_good_cigar) and (ic != len_cig - 1):
                            trim_right = trim_bad_cigars
                        else:
                            trim_right = 0
            
                        seqb = np.array(list(seq[trim_left:block_len - trim_right]), 'S1')
                        # Increment counts
                        for j, a in enumerate(alpha):
                            posa = (seqb == a).nonzero()[0]
                            if len(posa):
                                counts[js, j, pos + trim_left + posa] += 1
            
                    # Chop off this block
                    if ic != len_cig - 1:
                        seq = seq[block_len:]
                        pos += block_len
            
                # Deletion
                elif block_type == 2:
                    # Exclude bad CIGARs
                    if good_cigars[ic]: 
                        # Increment gap counts
                        counts[js, 4, pos:pos + block_len] += 1
            
                    # Chop off pos, but not sequence
                    pos += block_len
            
                # Insertion
                # an insert @ pos 391 means that seq[:391] is BEFORE the insert,
                # THEN the insert, FINALLY comes seq[391:]
                elif block_type == 1:
                    # Exclude bad CIGARs
                    if good_cigars[ic]: 
                        seqb = seq[:block_len]
                        inserts[pos][seqb][js] += 1
            
                    # Chop off seq, but not pos
                    if ic != len_cig - 1:
                        seq = seq[block_len:]
            
                # Other types of cigar?
                else:
                    raise ValueError('CIGAR type '+str(block_type)+' not recognized')

    return counts, inserts


def write_output_files(data_folder, adaID, fragment,
                       counts, inserts, coverage, subsample=False, VERBOSE=0):
    '''Write allele counts, inserts, and coverage to file'''
    if VERBOSE >= 1:
        print 'Write to file: '+'{:02d}'.format(adaID)+' '+fragment

    # Save counts and coverage
    counts.dump(get_allele_counts_filename(data_folder, adaID, fragment,
                                           subsample=subsample))
    coverage.dump(get_coverage_filename(data_folder, adaID, fragment,
                                        subsample=subsample))

    # Convert inserts to normal nested dictionary for pickle
    inserts_dic = {k: dict(v) for (k, v) in inserts.iteritems()}
    with open(get_insert_counts_filename(data_folder, adaID, fragment,
                                         subsample=subsample), 'w') as f:
        pickle.dump(inserts_dic, f, protocol=-1)





# Script
if __name__ == '__main__':

    # Input arguments
    parser = argparse.ArgumentParser(description='Get allele counts')
    parser.add_argument('--adaIDs', nargs='*', type=int,
                        help='Adapter IDs to analyze (e.g. 2 16)')
    parser.add_argument('--fragments', nargs='*',
                        help='Fragment to map (e.g. F1 F6)')
    parser.add_argument('--verbose', type=int, default=0,
                        help='Verbosity level [0-3]')
    parser.add_argument('--subsample', action='store_true',
                        help='Apply only to a subsample of the reads')
    parser.add_argument('--submit', action='store_true',
                        help='Execute the script in parallel on the cluster')

    args = parser.parse_args()
    adaIDs = args.adaIDs
    fragments = args.fragments
    VERBOSE = args.verbose
    subsample = args.subsample
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
    for adaID in adaIDs:
        for fragment in fragments:

            # Submit to the cluster self if requested
            if submit:
                fork_self(data_folder, adaID, fragment,
                          subsample=subsample, VERBOSE=VERBOSE)
                continue

            # Get counts
            counts, inserts = get_allele_counts(data_folder, adaID, fragment,
                                                subsample=subsample, VERBOSE=VERBOSE)

            # Get coverage
            coverage = counts.sum(axis=1)

            # Save to file
            write_output_files(data_folder, adaID, fragment,
                               counts, inserts, coverage,
                               subsample=subsample, VERBOSE=VERBOSE)