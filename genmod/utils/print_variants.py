#!/usr/bin/env python
# encoding: utf-8
"""
print_variants.py

Print the variants of a file to vcf file.

There are two modes, 'vcf' or 'modified'.
If 'vcf' we expect plain vcf variants and print them as they came in.
If 'modified' the first column has been used for sorting so we skip that one.

If a outfile is provided the variants will be printed to this one.

Created by Måns Magnusson on 2015-01-22.
Copyright (c) 2015 __MoonsoInc__. All rights reserved.
"""

from __future__ import print_function

from codecs import open


def print_variants(variant_file, outfile=None, mode='modified', silent=False):
    """
    Print the variants.
    
    If a result file is provided the variante will be appended to the file, 
    otherwise they are printed to stdout.
    
    There are two modes, 'vcf' or 'modified'.
    If 'vcf' we expect plain vcf variants and print them as they came in.
    If 'modified' the first column has been used for sorting so we skip 
    that one.
    
    Args:
        variants_file (str): A string with the path to a file
        outfile (str): Path to outfile or None
        mode (str): 'vcf' or 'modified'
        silent (bool): Bool. If nothing should be printed.
    
    """
    
    with open(variant_file, mode='r', encoding='utf-8') as f:
        if outfile:
            g = open(outfile, 'a', encoding='utf-8')
        
        for line in f:
            if not line.startswith('#'):
                line = line.rstrip().split('\t')
                if mode == 'modified':
                    line = line[1:]
                
                if outfile:
                    g.write('\t'.join(line)+'\n')
                
                else:
                    if not silent:
                        print('\t'.join(line))
    return

def print_variant_for_sorting(variant_line, outfile, family_id=None):
    """
    Print the variants for sorting
    
    Arguments:
        variant_line (str): A vcf variant line
        outfile (file_handle): A filehandle to the temporary variant file
        family_id (str): The family Id for sorting on rank score
    """
    variant_line = variant_line.split("\t")
    
    rank_score = -100
    for info_annotation in variant_line[7].split(';'):
        info_annotation = info_annotation.split('=')
        if len(info_annotation) == 2:
            key = info_annotation[0]
            value = info_annotation[1]
        if key == "RankScore":
            for family_annotation in value.split(','):
                family_annotation = family_annotation.split(':')
                if family_id:
                    # If we should sort on a certain family we look for the
                    # correct id
                    if family_id == family_annotation[0]:
                        rank_score = float(family_annotation[1])
                else:
                # If no family id is given we choose the first family found
                    rank_score = float(family_annotation[1])
                    break
    outfile.write("{0}\t{1}".format(rank_score, '\t'.join(variant_line)))
                    
