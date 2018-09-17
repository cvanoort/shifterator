"""
shifterator.py

Requires: Python 3

TODO:
- Add funcs to shift class that allow for easy updating of type2freq dicts
- Make it easy to remove / reset the filter. This will involve having to hold
  onto stop words, their freqs, and their values (discarded as of now)
- Make it so you can specify words as stop words instead of just a filter window
- Properly handle types without scores
- Add symbol when a type is borrowing a score from the other system
- Clean up class docstrings to fit standards of where things should be described
  (whether it's in init or under class, and listing what funcs are available)
"""

import os
import sys
import warnings
import numpy as np
import matplotlib.pyplot as plt
from plotting import *
from matplotlib import rc
from matplotlib import rcParams
from collections import Counter

from helper import *

# ------------------------------------------------------------------------------
# ---------------------------- GENERAL SHIFT CLASS -----------------------------
# ------------------------------------------------------------------------------
class Shift:
    def __init__(self, system_1, system_2, type2score_1=None, type2score_2=None,
                 reference_value=None, stop_lens=None, delimiter=','):
        """
        Shift object for calculating weighted scores of two systems of types,
        and the shift between them

        Parameters
        ----------
        system_1, system_2: dict
            keys are types of a system and values are frequencies
            of those types
        type2score_1, type2score_2: dict or str, optional
            if dict, types are keys and values are "scores" associated with each
            type (e.g., sentiment). If str, either the name of a score dict or
            file path to a score dict, where types and scores are given on each
            line, separated by commas. If None and other type2score is None,
            defaults to uniform scores across types. Otherwise defaults to the
            other type2score dict
        reference_value: float, optional
            the reference score from which to calculate the deviation. If None,
            defaults to the weighted score of system_1
        stop_lens: iterable of 2-tuples, optional
            denotes intervals that should be excluded when calculating shift
            scores
        """
        # Set type2freq dictionaries
        self.type2freq_1 = system_1
        self.type2freq_2 = system_2
        # Set type2score dictionaries
        if type2score_1 is not None and type2score_2 is not None:
            self.type2score_1 = get_score_dictionary(type2score_1, delimiter)
            self.type2score_2 = get_score_dictionary(type2score_2, delimiter)
        elif type2score_1 is not None:
            self.type2score_1 = get_score_dictionary(type2score_1, delimiter)
            self.type2score_2 = self.type2score_1
        elif type2score_2 is not None:
            self.type2score_2 = get_score_dictionary(type2score_2, delimiter)
            self.type2score_1 = self.type2score_2
        else:
            self.type2score_1 = {t : 1 for t in self.type2freq_1}
            self.type2score_2 = {t : 1 for t in self.type2freq_2}
        # Filter type dictionaries by stop lense
        self.stop_lens = stop_lens
        if stop_lens is not None:
            self.type2freq_1,self.type2score_1,sw_1 = filter_by_scores(type2freq_1,
                                                                       type2score_1,
                                                                       stop_lens)
            self.type2freq_2,self.type2score_2,sw_2 = filter_by_scores(type2freq_2,
                                                                       type2score_2,
                                                                       stop_lens)
            self.stop_words = sw_1.union(sw_2)
        # Get common vocabulary
        self.types = self.get_types(self.type2freq_1, self.type2score_1,
                                    self.type2freq_2, self.type2score_2)
        # Assume missing scores in each vocabulary (TODO: add options)
        self.type2score_1,self.type2score_2 = get_missing_scores (self.type2score_1,
                                                                  self.type2score_2)

        # Set reference value
        if reference_value is not None:
            self.reference_value = reference_value
        else:
            self.reference_value = self.get_weighted_score(self.type2freq_1,
                                                           self.type2score_1)
        # Set default score shift values
        self.diff = None
        self.type2p_diff = None
        self.type2s_diff = None
        self.type2p_avg = None
        self.type2s_ref_diff = None
        self.type2shift_score = None

    def get_types(self, type2freq_1, type2score_1, type2freq_2, type2score_2):
        """
        Returns the common "vocabulary" between the types of both systems and
        the types in the dictionaries

        Parameters
        ----------
        type2freq: dict
            keys are types and values are frequencies
        type2score: dict
            keys are types and values are scores
        """
        # Enforce common score vocabulary
        if len(set(type2score_1.keys()).difference(type2score_2.keys())) != 0:
            warning = 'Score dictionaries do not share a common vocabulary.'
            warnings.warn(warning, Warning)
        # Get observed types that are also in score dicts
        types_1 = set(type2freq_1.keys()).intersection(set(type2score_1.keys()))
        types_2 = set(type2freq_2.keys()).intersection(set(type2score_2.keys()))
        types = types_1.union(types_2)
        return types

    def get_weighted_score(self, type2freq, type2score):
        """
        Calculate the average score of the system specified by the frequencies
        and scores of the types in that system

        Parameters
        ----------
        type2freq: dict
            keys are types and values are frequencies
        type2score: dict
            keys are types and values are scores

        Returns
        -------
        s_avg: float
            Average weighted score of system
        """
        # Check we have a vocabulary to work with
        types = set(type2freq.keys()).intersection(set(type2score.keys()))
        if len(types) == 0:
            warning = 'No types in the frequency dict appear in the score dict'
            warnings.warn(warning, Warning)
            return
        # Get weighted score and total frequency
        f_total = sum([freq for t,freq in type2freq.items() if t in types])
        s_weighted = sum([type2score[t]*freq for t,freq in type2freq.items()
                          if t in types])
        s_avg = s_weighted / f_total
        return s_avg

    def get_shift_scores(self, type2freq_1=None, type2score_1=None,
                         type2freq_2=None, type2score_2=None,
                         reference_value=None, normalize=True, details=False):
        """
        Calculates the type shift scores between two systems

        Parameters
        ----------
        type2freq_1, type2freq_2: dict
            keys are types and values are frequencies. If None, defaults to the
            system_1 and system_2 type2freq dicts respectively
        type2score_1, type2score_2: dict
            keys are types and values are scores. If None, defaults to the
            system_1 and system_2 type2score dicts respectively
        reference_value: float
            the reference score from which to calculate the deviation. If None,
            defaults to the weighted score given by type2freq_1 and type2score_1
        normalize: bool
            if True normalizes shift scores so they sum to 1 or -1

        Returns
        -------
        type2p_diff: dict
            if details is True, returns dict where keys are types and values are
            the difference in relatively frequency, i.e. p_i,2 - p_i,1 for type i
        type2s_diff: dict,
            if details is True, returns dict where keys are types and values are
            the relative differences in score, i.e. s_i,2 - s_i,1 for type i
        type2p_avg: dict,
            if details is True, returns dict where keys are types and values are
            the average relative frequencies, i.e. 0.5*(p_i,1+p_i,2) for type i
        type2s_ref_diff: dict
            if details is True, returns dict where keys are types and values are
            relative deviation from reference score, i.e. 0.5*(s_i,2+s_i,1)-s_ref
            for type i
        type2shift_score: dict
            keys are types and values are shift scores
        """
        # Check input of type2freq and type2score dicts
        if type2freq_1 is None:
            type2freq_1 = self.type2freq_1
        if type2score_1 is None:
            type2score_1 = self.type2score_1
        if type2freq_2 is None:
            type2freq_2 = self.type2freq_2
        if type2score_2 is None:
            type2score_2 = self.type2score_2

        # Get type vocabulary
        types = self.get_types(type2freq_1, type2score_1,
                               type2freq_2, type2score_2)

        # Get total frequencies
        total_freq_1 = sum([freq for t,freq in type2freq_1.items() if t in types])
        total_freq_2 = sum([freq for t,freq in type2freq_2.items() if t in types])
        # Get relative frequency of types in both systems
        type2p_1 = {t:type2freq_1[t]/total_freq_1 if t in type2freq_1 else 0
                    for t in types}
        type2p_2 = {t:type2freq_2[t]/total_freq_2 if t in type2freq_2 else 0
                    for t in types}

        # Check input of reference value
        if reference_value is None:
            s_avg_ref = self.get_weighted_score(type2freq_1, type2score_1)

        # Calculate shift components
        type2p_avg = {}
        type2p_diff = {}
        type2s_diff = {}
        type2s_ref_diff = {}
        for t in types:
            type2p_avg[t] = 0.5*(type2p_1[t]+type2p_2[t])
            type2p_diff[t] = type2p_2[t]-type2p_1[t]
            type2s_diff[t] = type2score_2[t]-type2score_1[t]
            type2s_ref_diff[t] = 0.5*(type2score_2[t]+type2score_1[t])-s_avg_ref
            type2shift_score[t] = type2p_diff[t]*type2s_ref_diff[t]\
                                  +type2s_diff[t]*type2p_avg[t]

        # Normalize the total shift scores
        total_diff = sum(type2shift_score.values())
        self.diff = total_diff
        if normalize:
            type2shift_score = {t : shift_score/abs(total_diff) for t,shift_score
                                in type2shift_score.items()}

        # Set results in shift object (TODO: is this unexpected behavior?)
        self.type2p_diff = type2p_diff
        self.type2s_diff = type2s_diff
        self.type2p_avg = type2p_avg
        self.type2s_ref_diff = type2s_ref_diff
        self.type2shift_score = type2shift_score
        # Return shift scores
        if details:
            return type2p_diff,type2s_diff,type2p_avg,type2s_ref_diff,type2shift_score
        else:
            return type2shift_score

    def get_shift_component_sums(self, type2freq_1=None, type2score_1=None,
                                 type2freq_2=None, type2score_2=None,
                                 reference_value=None, normalize=True):
        """

        """
        # Check input of type2freq and type2score dicts
        if type2freq_1 is None:
            type2freq_1 = self.type2freq_1
        if type2score_1 is None:
            type2score_1 = self.type2score_1
        if type2freq_2 is None:
            type2freq_2 = self.type2freq_2
        if type2score_2 is None:
            type2score_2 = self.type2score_2
        # Get shift scores
        if self.type2shift_score is None:
            shift_scores = self.get_shift_scores(type2freq_1, type2score_1,
                                                 type2freq_2, type2score_2,
                                                 reference_value, normalize,
                                                 details=True)
        else:
            shift_scores = [(t, self.type2p_diff[t], self.type2s_diff[t],
                             self.type2p_avg[t], self.type2s_ref_diff[t],
                             self.type2shift_score[t]) for t in self.type2s_diff]

        # Sum up components of shift score
        pos_freq_pos_score = 0
        pos_freq_neg_score = 0
        neg_freq_pos_score = 0
        neg_freq_neg_score = 0
        pos_s_diff = 0
        neg_s_diff = 0
        for t,p_diff,s_diff,p_avg,s_ref_diff, _ in shift_scores:
            # Get contribution of p_diff*s_ref_diff term
            if p_diff > 0:
                if s_ref_diff > 0:
                    pos_freq_pos_score += p_diff*s_ref_diff
                else:
                    pos_freq_neg_score += p_diff*s_ref_diff
            else:
                if s_ref_diff > 0:
                    neg_freq_pos_score += p_diff*s_ref_diff
                else:
                    neg_freq_neg_score += p_diff*s_ref_diff
            # Get contribution of s_diff term
            if s_diff > 0:
                pos_s_diff += p_avg*s_diff
            else:
                neg_s_diff += p_avg*s_diff

        return (pos_freq_pos_score, pos_freq_neg_score,
                neg_freq_pos_score, neg_freq_neg_score,
                pos_s_diff, neg_s_diff)

    def get_shift_graph(self, top_n=50, text_size_inset=True, cumulative_inset=True,
                        show_plot=True, filename=None, **kwargs):
        """
        Plot the simple shift graph between two systems of types

        Parameters
        ----------
        top_n: int
            display the top_n types as sorted by their absolute contribution to
            the difference between systems
        cumulative_inset, text_size_inset: bool
            whether to show insets showing the cumulative contribution to the
            shift by ranked types, and the relative sizes of each system
        show_plot: bool
            whether to show plot on finish

        Returns
        -------
        ax
            matplotlib ax of shift graph. Displays shift graph if show_plot=True
        """
        # Set plotting parameters
        kwargs = get_plotting_params(kwargs)

        # Get type score components
        if self.type2shift_score is None:
            self.get_shift_scores(details=False)
        type_scores = [(t, self.type2p_diff[t], self.type2s_diff[t],
                        self.type2p_avg[t], self.type2s_ref_diff[t],
                        self.type2shift_score[t]) for t in self.type2s_diff]
        # Reverse sorting to get highest scores, then reverse top n for plotting
        type_scores = sorted(type_scores, key=lambda x:abs(x[-1]),
                             reverse=True)[:top_n]
        type_scores.reverse()

        # Get bar heights and colors
        bar_heights = get_bar_heights(type_scores, abs(self.diff))
        bar_colors = get_bar_colors(type_scores, bar_heights, kwargs)
        # Initialize plot
        f,ax = plt.subplots(figsize=(kwargs['width'], kwargs['height']))
        ax.margins(kwargs['y_margin'])
        # Plot type contributions
        ax = plot_contributions(ax, bar_heights, bar_colors, kwargs)
        # Plot total sum contributions
        ax,comp_bars = plot_total_contribution_sums(ax, total_comp_sums,
                                                    bar_heights[-1], kwargs)
        # Adjust top bars for correct direction of labels
        for i in [1, 3, 5]:
            if comp_bars[i] == 0:
                comp_bars[i] = -0.0000000001

        # Get labels for bars
        type_labels = [t for (t,_,_,_,_,_) in type_scores]
        # Set font type
        if kwargs['serif']:
            set_serif()
        # Add labels to bars
        ax = set_bar_labels(f, ax, type_labels, bar_heights[-1], comp_bars, kwargs)

        # Add center dividing line
        y_min,y_max = ax.get_ylim()
        ax.plot([0,0],[1,y_max], '-', color='black', linewidth=0.7)
        # Add dividing line between words and component bars
        x_min,x_max = ax.get_xlim()
        ax.plot([x_min,x_max], [top_n+1,top_n+1], '-', color='black',
                 linewidth=0.7)
        ax.plot([x_min,x_max], [top_n+2.75, top_n+2.75], '-', color='black',
                linewidth=0.5)

        # Set cumulative diff inset
        if cumulative_inset:
            f = get_cumulative_inset(f, self.type2shift_score, top_n, kwargs)
        if text_size_inset:
            f = get_text_size_inset(f, self.type2freq_1, self.type2freq_2, kwargs)
        # Set guidance arrows (for relative plot)
        #if guidance:
        #    ax = get_guidance_annotations(ax, top_n, annotation_text=None)

        # Make x-tick labels bigger, flip y-axis ticks and label every 5th one
        ax = set_ticks(ax, top_n, kwargs)
        # Set axis labels and title
        ax.set_xlabel(kwargs['xlabel'], fontsize=kwargs['xlabel_fontsize'])
        ax.set_ylabel(kwargs['ylabel'], fontsize=kwargs['ylabel_fontsize'])
        if title not in kwargs:
            s_avg_1 = self.get_weighted_score(self.type2freq_1,self.type2score_1)
            s_avg_2 = self.get_weighted_score(self.type2freq_2,self.type2score_2)
            title = r'$\Phi_{\Omega^{(2)}}$: $s_{avg}^{(1)}=$'+'{0:.2f}'\
                    .format(s_avg_1)+'\n'\
                    +r'$\Phi_{\Omega^{(1)}}$: $s_{avg}^{(2)}=$'+'{0:.2f}'\
                    .format(s_avg_2)
            kwargs['title'] = title
        ax.set_title(kwargs['title'], fontsize=kwargs['title_fontsize'])

        # Show and return plot
        if kwargs['tight']:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                plt.tight_layout()
        if filename is not None:
            plt.savefig(filename, dpi=425)
        if show_plot:
            plt.show()
        return ax

# ------------------------------------------------------------------------------
# ------------------------------ HELPER FUNCTIONS ------------------------------
# ------------------------------------------------------------------------------
def filter_by_scores(type2freq, type2score, stop_lens):
    """
    Loads a dictionary of type scores

    Parameters
    ----------
    type2freq: dict
        keys are types, values are frequencies of those types
    type2score: dict
        keys are types, values are scores associated with those types
    stop_lens: iteratble of 2-tuples
        denotes intervals that should be excluded when calculating shift scores

    Returns
    -------
    type2freq_new,type2score_new: dict,dict
        Frequency and score dicts filtered of words whose score fall within stop
        window
    """
    type2freq_new = dict()
    type2score_new = dict()
    stop_words = set()
    for lower_stop,upper_stop in stop_lens:
        for t in type2score:
            if ((type2score[t] < lower_stop) or (type2score[t] > upper_stop))\
            and t not in stop_words:
                try:
                    type2freq_new[t] = type2freq[t]
                except KeyError:
                    pass
                type2score_new[t] = type2score[t]
            else:
                stop_words.add(t)

    return (type2freq_new, type2score_new, stop_words)

def get_score_dictionary(scores, delimiter=','):
    """
    Loads a dictionary of type scores

    Parameters
    ----------
    scores: dict or str
        if dict, then returns the dict automatically. If str, then it is either
        the name of a shifterator dictionary to load, or file path of dictionary
        to load. File should be two columns of types and scores on each line,
        separated by delimiter
            Options: 'labMT_english'
    stop_lens: iteratble of 2-tuples
        denotes intervals that should be excluded when calculating shift scores
    delimiter: str
        delimiter used in the dictionary file

    Returns
    -------
    type2score, dict
        dictionary where keys are types and values are scores of those types
    """
    if type(scores) is dict:
        return scores
    # Check if dictionary name is in shifterator data
    score_dicts = os.listdir('data')
    if scores in score_dicts:
        dict_file = 'data/'+scores
    elif  scores+'.csv' in score_dicts:
        dict_file = 'data/'+scores+'.csv'
    else: # Assume file path
        dict_file = scores
    # Load score dictionary
    type2score = {}
    with open(dict_file, 'r') as f:
        for line in f:
            t,score = line.strip().split(delimiter)
            type2score[t] = score

    return type2score

def get_missing_scores (type2score_1, type2score_2):
    """
    Get missing scores between systems by setting the score in one system with
    the score in the other system

    Parameters
    ----------
    type2score_1, type2score_2: dict
        keys are types and values are scores

    Output
    ------
    type2score_1, type2score_2: dict
        keys are types and values are scores, updated to have scores across all
        types between the two score dictionaries
    """
    types = set(type2score_1.keys()).union(set(type2score_2.keys()))
    for t in types:
        if t not in type2score_1:
            type2score_1[t] = type2score_2[t]
        elif t not in type2score_2:
            type2score_2[t] = type2score_1[t]
    return (type2score_1, type2score_2)
