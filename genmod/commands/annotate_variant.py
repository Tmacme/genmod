#!/usr/bin/env python
# encoding: utf-8
"""
annotate_variants.py

Command line tool for annotating vcf variants.
How and what that should be annotated is specified on the command line or with a config file.


Created by Måns Magnusson on 2015-08-25.
Copyright (c) 2015 __MoonsoInc__. All rights reserved.
"""

from __future__ import (print_function)

import sys
import os
import logging
import pkg_resources

import click
import tabix

from multiprocessing import JoinableQueue, Manager, cpu_count
from codecs import open
from tempfile import NamedTemporaryFile
from datetime import datetime

from genmod import __version__
# from genmod.annotate_regions import load_annotations, check_overlap
from genmod.vcf_tools import (HeaderParser, add_vcf_info, add_metadata, 
print_headers, print_variant, sort_variants)

from genmod.annotate_variants import VariantAnnotator
from genmod.annotate_regions import (get_genes, check_exonic, load_annotations)
from genmod.utils import VariantPrinter

@click.command()
@click.argument('variant_file',
                    nargs=1,
                    type=click.File('r'),
                    metavar='<vcf_file> or -'
)
@click.option('-r', '--annotate_regions', 
                is_flag=True,
                help='Increase output verbosity.'
)
@click.option('--cadd_file', 
                    type=click.Path(exists=True), 
                    help="""Specify the path to a bgzipped cadd file (with index) with variant scores."""
)
@click.option('--cadd_1000g',
                    type=click.Path(exists=True), 
                    help="""Specify the path to a bgzipped cadd file (with index) with variant scores 
                            for all 1000g variants."""
)
@click.option('--cadd_exac',
                    type=click.Path(exists=True), 
                    help="""Specify the path to a bgzipped cadd file (with index) with variant scores 
                            for all ExAC variants."""
)
@click.option('--cadd_esp',
                    type=click.Path(exists=True), 
                    help="""Specify the path to a bgzipped cadd file (with index) with variant scores 
                            for all ESP6500 variants."""
)
@click.option('--cadd_indels',
                    type=click.Path(exists=True), 
                    help="""Specify the path to a bgzipped cadd file (with index) with variant scores 
                            for all CADD InDel variants."""
)
@click.option('--thousand_g',
                    type=click.Path(exists=True), 
                    help="""Specify the path to a bgzipped vcf file (with index) with 1000g variants"""
)
@click.option('--exac',
                    type=click.Path(exists=True), 
                    help="""Specify the path to a bgzipped vcf file (with index) with exac variants."""
)
@click.option('-a' ,'--annotation_dir',
                    type=click.Path(exists=True),
                    default=pkg_resources.resource_filename('genmod', 'annotations'),
                    help="""Specify the path to the directory where the annotation 
                    databases are. 
                    Default is the gene pred files that comes with the distribution."""
)
@click.option('-o', '--outfile', 
                    type=click.File('w'),
                    help='Specify the path to a file where results should be stored.'
)
@click.option('-s', '--silent',
                is_flag=True,
                help='Do not print the variants.'
)
@click.option('--cadd_raw', 
                    is_flag=True,
                    help="""If the raw cadd scores should be annotated."""
)
@click.option('-p', '--processes', 
                default=min(4, cpu_count()),
                help='Define how many processes that should be use for annotation.'
)
def annotate(variant_file, annotate_regions, cadd_file, cadd_1000g, 
cadd_exac, cadd_esp, cadd_indels, thousand_g, exac, annotation_dir, 
outfile, silent, cadd_raw, processes):
    """
    Annotate vcf variants.
    
    Annotate variants with a number of different sources.
    Please use --help for more info.
    """

    logger = logging.getLogger(__name__)
    #For testing
    logger = logging.getLogger("genmod.commands.annotate_variants")
    
    logger.info("Running genmod annotate_variant version {0}".format(__version__))
    
    start_time_analysis = datetime.now()
    
    annotator_arguments = {}
    annotator_arguments['cadd_raw'] = cadd_raw
    
    logger.info("Initializing a Header Parser")
    head = HeaderParser()
    
    for line in variant_file:
        line = line.rstrip()

        if line.startswith('#'):
            if line.startswith('##'):
                head.parse_meta_data(line)
            else:
                head.parse_header_line(line)
        else:
            break
    
    header_line = head.header
    annotator_arguments['header_line'] = header_line
    
    if annotate_regions:
        logger.info("Loading annotations")
        gene_trees, exon_trees = load_annotations(annotation_dir)
        annotator_arguments['gene_trees'] = gene_trees
        annotator_arguments['exon_trees'] = exon_trees
        
        add_metadata(
            head,
            'info',
            'Annotation',
            annotation_number='.',
            entry_type='String',
            description='Annotates what feature(s) this variant belongs to.'
        )
        add_metadata(
            head,
            'info',
            'Exonic',
            annotation_number='0',
            entry_type='Flag',
            description='Indicates if the variant is exonic.'
        )
        
    variant_file.seek(0)
    
    if exac:
        annotator_arguments['exac'] = exac
        add_metadata(
            head,
            'info',
            'ExACAF',
            annotation_number='A',
            entry_type='Float',
            description="Frequency in the ExAC database."
        )
        
    if thousand_g:
        annotator_arguments['thousand_g'] = thousand_g
        logger.debug("Adding vcf metadata for 1000G_freq")
        add_metadata(
            head,
            'info',
            '1000GAF',
            annotation_number='A',
            entry_type='Float',
            description="Frequency in the 1000G database."
        )
    
    any_cadd_file = False

    if cadd_file:
        annotator_arguments['cadd_file'] = cadd_file
        any_cadd_file = True

    if cadd_1000g:
        annotator_arguments['cadd_1000g'] = cadd_1000g
        any_cadd_file = True

    if cadd_exac:
        annotator_arguments['cadd_exac'] = cadd_exac
        any_cadd_file = True

    if cadd_esp:
        annotator_arguments['cadd_ESP'] = cadd_esp
        any_cadd_file = True

    if cadd_indels:
        annotator_arguments['cadd_InDels'] = cadd_indels
        any_cadd_file = True
    
    if any_cadd_file:
        add_metadata(
            head,
            'info',
            'CADD',
            annotation_number='A',
            entry_type='Float',
            description="The CADD relative score for this alternative."
        )
        if cadd_raw:
            annotator_arguments['cadd_raw'] = True
            logger.debug("Adding vcf metadata for CADD raw score")
            add_metadata(
                head,
                'info',
                'CADD_raw',
                annotation_number='A',
                entry_type='Float',
                description="The CADD raw score(s) for this alternative(s)."
            )
    
    ###################################################################
    ### The task queue is where all jobs(in this case batches that  ###
    ### represents variants in a region) is put. The consumers will ###
    ### then pick their jobs from this queue.                       ###
    ###################################################################

    logger.debug("Setting up a JoinableQueue for storing variant batches")
    variant_queue = JoinableQueue(maxsize=1000)
    logger.debug("Setting up a Queue for storing results from workers")
    results = Manager().Queue()
    
    num_annotators = processes
    #Adapt the number of processes to the machine that run the analysis
    if any_cadd_file:
        # We need more power when annotating cadd scores:
        # But if flag is used that overrides
        if num_annotators == min(4, cpu_count()):
            num_annotators = min(8, cpu_count())

    logger.info('Number of CPU:s {}'.format(cpu_count()))
    logger.info('Number of model checkers: {}'.format(num_annotators))

    # We use a temp file to store the processed variants
    logger.debug("Build a tempfile for printing the variants")
    temp_file = NamedTemporaryFile(delete=False)
    temp_file.close()

    # These are the workers that do the heavy part of the analysis
    logger.info('Seting up the workers')
    annotators = [
        VariantAnnotator(
            variant_queue, 
            results, 
            **annotator_arguments
        )
        for i in range(num_annotators)
    ]

    logger.info('Starting the workers')
    for worker in annotators:
        logger.debug('Starting worker {0}'.format(worker))
        worker.start()

    # This process prints the variants to temporary files
    logger.info('Seting up the variant printer')
    var_printer = VariantPrinter(
                    task_queue = results, 
                    head = head, 
                    mode='chromosome', 
                    outfile = temp_file.name
                    )
    
    logger.info('Starting the variant printer process')
    var_printer.start()

    start_time_variant_parsing = datetime.now()

    # This process parses the original vcf and create batches to put in the variant queue:
    logger.info('Start parsing the variants')
    
    for line in variant_file:
        line = line.rstrip()
        
        if not line.startswith('#'):
            variant_queue.put(line)
    
    logger.info('Put stop signs in the variant queue')
    
    for i in range(num_annotators):
        variant_queue.put(None)

    variant_queue.join()
    results.put(None)
    var_printer.join()

    logger.info("Start sorting the variants")
    sort_variants(temp_file.name, mode='chromosome')

    logger.info("Print the headers")
    print_headers(head, outfile, silent)

    with open(temp_file.name, 'r', encoding='utf-8') as f:
        for line in f:
            print_variant(
                variant_line=line,
                outfile=outfile,
                mode='modified',
                silent=silent
            )

    logger.info("Removing temp file")
    os.remove(temp_file.name)
    logger.debug("Temp file removed")

    logger.info('Time for whole analyis: {0}'.format(
        str(datetime.now() - start_time_analysis)))
    
    # for line in variant_file:
    #     line = line.rstrip()
    #
    #     if not line.startswith('#'):
    #         splitted_line = line.split()
    #         chrom = splitted_line[0].strip('chr')
    #         position = int(splitted_line[1])
    #         ref = splitted_line[3]
    #         alternatives = splitted_line[4]
    #
    #         longest_alt = max([
    #             len(alt) for alt in alternatives.split(',')])
    #
    #         if annotate_regions:
    #             if check_exonic(
    #                 chrom = chrom,
    #                 start = position,
    #                 stop = (position+longest_alt)-1,
    #                 exon_trees = exon_trees):
    #                 line = add_vcf_info(
    #                     keyword = 'Exonic',
    #                     variant_line=line,
    #                     annotation=None
    #                 )
    #
    #             genes = get_genes(
    #                 chrom = chrom,
    #                 start = position,
    #                 stop = (position+longest_alt)-1,
    #                 gene_trees = gene_trees
    #             )
    #             if genes:
    #                 line = add_vcf_info(
    #                     keyword = "Annotation",
    #                     variant_line = line,
    #                     annotation = ','.join(genes)
    #                 )
                    
                
            # annotated_line = annotate_thousand_g(
            #     variant_line = line,
            #     thousand_g = thousand_g_handle
            # )

if __name__ == '__main__':
    from genmod.log import init_log
    from genmod import logger
    init_log(logger, loglevel="INFO")
    annotate()
