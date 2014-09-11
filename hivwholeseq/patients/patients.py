# vim: fdm=marker
'''
author:     Fabio Zanini
date:       23/10/13
content:    Description module for HIV patients.
'''
# Modules
import numpy as np
import pandas as pd

from hivwholeseq.sequencing.filenames import table_filename



# Classes
class Patient(pd.Series):
    '''HIV patient'''

    def __init__(self, *args, **kwargs):
        '''Initialize a patient with all his samples'''
        super(Patient, self).__init__(*args, **kwargs)
        samples = load_samples_sequenced(patients=[self.name])
        self.samples = samples


    @property
    def _constructor(self):
        return Patient


    @property
    def folder(self):
        '''The folder with the data on this patient'''
        from hivwholeseq.patients.filenames import get_foldername
        return str(get_foldername(self.name))


    def discard_nonsequenced_samples(self):
        '''Discard all samples that have not been sequenced yet'''
        from hivwholeseq.sequencing.samples import load_samples_sequenced as lss
        samples_sequenced = lss()
        samples_sequenced_set = set(samples_sequenced.loc[:, 'patient sample']) - set(['nan'])
        samples = self.samples.loc[self.samples.index.isin(samples_sequenced_set)]

        # Add info on sequencing
        samples_seq_col = []
        for samplename in samples.index:
            ind = samples_sequenced.loc[:, 'patient sample'] == samplename
            samples_seq_col.append(samples_sequenced.loc[ind])
        samples['samples seq'] = samples_seq_col

        self.samples = samples


    @property
    def dates(self):
        '''Get the dates of sampling'''
        return self.samples.date

    
    @property
    def times(self, unit='day'):
        '''Get the times from transmission'''
        return convert_date_deltas_to_float(self.dates - self.transmission_date, unit=unit)


    @property
    def viral_load(self):
        '''Get the time course of the viral load'''
        return self.samples['viral load']


    @property
    def initial_sample(self):
        '''The initial sample used as a mapping reference'''
        return self.samples.iloc[0]


    def itersamples(self):
        '''Generator for samples in this patient, each with extended attributes'''
        for samplename, sample in self.samples.iterrows():
            yield SamplePat(sample)


    def get_reference_filename(self, fragment, format='fasta'):
        '''Get filename of the reference for mapping'''
        from hivwholeseq.patients.filenames import get_initial_reference_filename
        return get_initial_reference_filename(self.name, fragment, format)


    def get_reference(self, fragment):
        '''Get the reference for a fragment'''
        from Bio import SeqIO
        return SeqIO.read(self.get_reference_filename(fragment), 'fasta')


    def get_consensi_alignment_filename(self, fragment):
        '''Get the multiple sequence alignment of all consensi'''
        from hivwholeseq.patients.filenames import get_consensi_alignment_filename
        return get_consensi_alignment_filename(self.name, fragment)


    def get_consensi_tree_filename(self, fragment):
        '''Get the filename of the consensi of the patient'''
        from hivwholeseq.patients.filenames import get_consensi_tree_filename
        return get_consensi_tree_filename(self.name, fragment)


    def get_coverage_trajectories(self, fragment, use_PCR1=1):
        '''Get coverage as a function of time'''
        (act, ind) = self.get_allele_count_trajectories(fragment, use_PCR1=use_PCR1)
        return (act.sum(axis=1), ind)


    def get_allele_frequency_trajectories(self, fragment, use_PCR1=1, cov_min=1):
        '''Get the allele frequency trajectories from files
        
        Args:
          cov_min (int): minimal coverage accepted, anything lower will be masked.
        '''
        (act, ind) = self.get_allele_count_trajectories(fragment, use_PCR1=use_PCR1)

        covt = act.sum(axis=1)
        mask = np.zeros_like(act, bool)
        mask.swapaxes(0, 1)[:] = covt < cov_min

        # NOTE: the hard mask is necessary to avoid unmasking part of the alphabet
        # at a certain site: the mask is site-wise, not allele-wise
        aft = np.ma.array((1.0 * act.swapaxes(0, 1) / covt).swapaxes(0, 1),
                          mask=mask,
                          hard_mask=True,
                          fill_value=0)

        aft[(aft < 1e-4)] = 0
        # NOTE: we'd need to renormalize, but it's a small effect

        return (aft, ind)


    def get_allele_count_trajectories(self, fragment, use_PCR1=1):
        '''Get the allele count trajectories from files'''
        from hivwholeseq.patients.one_site_statistics import get_allele_count_trajectories
        from operator import itemgetter
        (sns, act) = get_allele_count_trajectories(self.name, self.samples.index,
                                                   fragment,
                                                   use_PCR1=use_PCR1, VERBOSE=0)
        ind = [i for i, (_, sample) in enumerate(self.samples.iterrows())
               if sample.name in map(itemgetter(0), sns)]
        return (act, ind)


    def get_mapped_filtered_filename(self, samplename, fragment, PCR=1):
        '''Get filename(s) of mapped and filtered reads for a sample'''
        from hivwholeseq.patients.filenames import get_mapped_filtered_filename
        return get_mapped_filtered_filename(self.patient, samplename, fragment, PCR=PCR)


    @property
    def transmission_date(self):
        '''The most likely time of transmission'''
        return self['last negative date'] + \
                (self['first positive date'] - self['last negative date']) / 2


class SamplePat(pd.Series):
    '''Patient sample'''

    def __init__(self, *args, **kwargs):
        '''Initialize a patient sample'''
        super(SamplePat, self).__init__(*args, **kwargs)


    @property
    def _constructor(self):
        return SamplePat


    def get_mapped_filtered_filename(self, fragment, PCR=1):
        '''Get filename(s) of mapped and filtered reads'''
        from hivwholeseq.patients.filenames import get_mapped_filtered_filename
        return get_mapped_filtered_filename(self.patient, self.name, fragment, PCR=PCR)


    def get_mapped_filenames(self, fragment, PCR=1):
        '''Get filename(s) of mapped and filtered reads'''
        # TODO: optimize this call
        from hivwholeseq.patients.filenames import get_mapped_to_initial_filename
        from hivwholeseq.sequencing.samples import load_samples_sequenced as lss
        samples_seq = lss()
        samples_seq = samples_seq.loc[samples_seq['patient sample'] == self.name]

        fns = [get_mapped_to_initial_filename(self.patient, self.name, samplename,
                                              PCR=PCR)
               for samplename, sample in samples_seq.iterrows()]
        return fns


    def get_allele_counts_filename(self, fragment, PCR=1, qual_min=30):
        '''Get the filename of the allele counts'''
        from hivwholeseq.patients.filenames import get_allele_counts_filename
        return get_allele_counts_filename(self.patient, self.name, fragment,
                                          PCR=PCR, qual_min=qual_min)




# Functions
def load_patients():
    '''Load patients from general table'''
    patients = pd.read_excel(table_filename, 'Patients',
                             index_col=0)
    patients.index = pd.Index(map(str, patients.index))
    return patients


def load_patient(pname):
    '''Get the patient from the sequences ones'''
    patients = load_patients()
    patient = Patient(patients.loc[pname])
    return patient


def load_samples_sequenced(patients=None):
    '''Load patient samples sequenced from general table'''
    sample_table = pd.read_excel(table_filename, 'Samples timeline sequenced',
                                 index_col=0)

    sample_table.index = pd.Index(map(str, sample_table.index))
    sample_table.loc[:, 'patient'] = map(str, sample_table.loc[:, 'patient'])
    # FIXME: the number of molecules to PCR depends on the number of
    # fragments for that particular experiment... integrate Lina's table!
    # Note: this refers to the TOTAL # of templates, i.e. the factor 2x for
    # the two parallel RT-PCR reactions
    sample_table['n templates'] = sample_table['viral load'] * 0.4 / 12 * 2

    if patients is not None:
        sample_table = sample_table.loc[sample_table.loc[:, 'patient'].isin(patients)]

    return sample_table


def filter_patients_n_times(patients, n_times=3):
    '''Find what patients have at least n_times time points sequenced'''
    ind = np.zeros(len(patients), bool)
    for i, (pname, patient) in enumerate(patients.iterrows()):
        patient = Patient(patient)
        patient.discard_nonsequenced_samples()
        if len(patient.times) >= n_times:
            ind[i] = True

    return ind


def convert_date_deltas_to_float(deltas, unit='day'):
    '''Convert pandas date deltas into float'''
    nanoseconds_per_unit = {'day': 3600e9 * 24,
                            'month': 3600e9 * 24 * 365.25 / 12,
                            'year': 3600e9 * 24 * 365.25,
                           }
    return np.array(deltas, float) / nanoseconds_per_unit[unit]
