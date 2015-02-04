# vim: fdm=marker
'''
author:     Fabio Zanini
date:       11/09/14
content:    Grab all consensi from a patient and align them.
'''
# Modules
import sys
import os
import argparse
from operator import attrgetter
import numpy as np
from Bio import SeqIO, AlignIO

from hivwholeseq.utils.generic import mkdirs
from hivwholeseq.patients.patients import load_patients, Patient, SamplePat
from hivwholeseq.utils.tree import build_tree_fasttree
from hivwholeseq.utils.mapping import align_muscle



# Functions
def trim_to_refseq(seq, refseq):
    '''Trim sequence to a reference sequence'''
    from seqanpy import align_overlap

    (score, ali1, ali2) = align_overlap(seq, refseq, score_gapopen=-20)
    start = len(ali2) - len(ali2.lstrip('-'))
    end = len(ali2.rstrip('-'))

    return seq[start: end]



# Script
if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Align consensi',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)    
    parser.add_argument('--patients', nargs='+', default=['all'],
                        help='Patients to analyze')
    parser.add_argument('--regions', nargs='*',
                        help='Regions to analyze (e.g. V3 F6)')
    parser.add_argument('--verbose', type=int, default=0,
                        help='Verbosity level [0-4]')
    parser.add_argument('--save', action='store_true',
                        help='Save alignment to file')

    args = parser.parse_args()
    pnames = args.patients
    regions = args.regions
    VERBOSE = args.verbose
    use_save = args.save

    patients = load_patients()
    if pnames != ['all']:
        patients = patients.iloc[patients.index.isin(pnames)]

    for pname, patient in patients.iterrows():
        patient = Patient(patient)
        patient.discard_nonsequenced_samples()

        if regions is None:
            refseq_gw = patient.get_reference('genomewide', 'gb')
            regionspat = map(attrgetter('id'), refseq_gw.features) + ['genomewide']
        else:
            regionspat = regions

        for region in regionspat:
            if VERBOSE >= 1:
                print pname, region
                if VERBOSE == 1:
                    print ''

            # FIXME: tat and rev are messed up still!
            refseq = patient.get_reference(region)
            refseq.id = 'reference_'+refseq.id
            refseq.name = 'reference_'+refseq.name
            refseq.description = 'reference '+refseq.description
            seqs = [refseq]

            (fragment, start, stop) = patient.get_fragmented_roi(region, VERBOSE=0,
                                                                 include_genomewide=True)

            for i, (samplename, sample) in enumerate(patient.samples.iterrows()):
                if VERBOSE >= 2:
                    print samplename,

                sample = SamplePat(sample)
                fn = sample.get_consensus_filename(fragment)
                if os.path.isfile(fn):
                    cons_seq = SeqIO.read(fn, 'fasta')
                    cons_seq.id = str(patient.times[i])+'_'+cons_seq.id
                    cons_seq.name = cons_seq.id
                    cons_reg = trim_to_refseq(cons_seq, refseq)
                    seqs.append(cons_reg)
                    if VERBOSE >= 2:
                        print 'OK'

                else:
                    if VERBOSE >= 2:
                        print 'MISS'
                    continue

                    
            if VERBOSE >= 2:
                print 'Align',
            ali = align_muscle(*seqs, sort=True)
            if VERBOSE >= 2:
                print 'OK'


            if use_save:
                if VERBOSE >= 2:
                    print 'Save',
                fn_out = patient.get_consensi_alignment_filename(region)
                mkdirs(os.path.dirname(fn_out))
                AlignIO.write(ali, fn_out, 'fasta')
                if VERBOSE >= 2:
                    print 'OK'