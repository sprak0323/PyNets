# -*- coding: utf-8 -*-
"""
Created on Tue Nov  7 10:40:07 2017

@author: Derek Pisner
"""
import sys
import os
import numpy as np
import pandas as pd
import nibabel as nib
import warnings
warnings.simplefilter("ignore")
from pathlib import Path
from nilearn import input_data
from nilearn import plotting as niplot
from pynets import nodemaker, thresholding, plotting, graphestimation, utils
from pynets.diffconnectometry import prepare_masks, run_struct_mapping
from pynets.utils import convert_atlas_to_volumes
try:
    import cPickle as pickle
except ImportError:
    import _pickle as pickle

def wb_functional_connectometry(input_file, ID, atlas_select, network, node_size, mask, thr, parlistfile, all_nets, conn_model, dens_thresh, conf, adapt_thresh, plot_switch, bedpostx_dir, anat_loc, parc, ref_txt, procmem):

    ##Input is nifti file
    func_file=input_file

    ##Test if atlas_select is a nilearn atlas. If so, fetch coords, labels, and/or networks.
    nilearn_atlases=['atlas_aal', 'atlas_craddock_2012', 'atlas_destrieux_2009']
    if atlas_select in nilearn_atlases:
        [label_names, networks_list, parlistfile] = utils.nilearn_atlas_helper(atlas_select)

    ##Get coordinates and/or parcels from atlas
    if parlistfile is None and parc == False:
        print('Fetching coordinates and labels from nilearn coordinate-based atlases')
        ##Fetch nilearn atlas coords
        [coords, atlas_select, networks_list, label_names] = nodemaker.fetch_nilearn_atlas_coords(atlas_select)
    else:
        ##Fetch user-specified atlas coords
        [coords, atlas_select, par_max, parcel_list] = nodemaker.get_names_and_coords_of_parcels(parlistfile)

        ##Describe user atlas coords
        print('\n' + atlas_select + ' comes with {0} '.format(par_max) + 'parcels' + '\n')
        print('\n'+ 'Stacked atlas coordinates in array of shape {0}.'.format(coords.shape) + '\n')

    ##Labels prep
    try:
        label_names
    except:
        if ref_txt is not None and os.path.exists(ref_txt):
            atlas_select = os.path.basename(ref_txt).split('.txt')[0]
            dict_df = pd.read_csv(ref_txt, sep=" ", header=None, names=["Index", "Region"])
            label_names = dict_df['Region'].tolist()
        else:
            try:
                atlas_ref_txt = atlas_select + '.txt'
                ref_txt = Path(__file__)/'atlases'/atlas_ref_txt
                dict_df = pd.read_csv(ref_txt, sep=" ", header=None, names=["Index", "Region"])
                label_names = dict_df['Region'].tolist()
            except:
                label_names = np.arange(len(coords) + 1)[np.arange(len(coords) + 1) != 0].tolist()

    ##Get subject directory path
    dir_path = os.path.dirname(os.path.realpath(func_file)) + '/' + atlas_select
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

    ##Mask coordinates
    if mask is not None:
        if parc == True:
            [coords, label_names, parcel_list_masked] = nodemaker.parcel_masker(mask, coords, parcel_list, label_names, dir_path, ID)
            [net_parcels_map_nifti, parcel_list_adj] = nodemaker.create_parcel_atlas(parcel_list_masked)     
            net_parcels_nii_path = dir_path + '/' + ID + '_parcels_masked_' + str(os.path.basename(mask).split('.')[0]) + '.nii.gz'
            nib.save(net_parcels_map_nifti, net_parcels_nii_path)
        elif parc == False:
            [coords, label_names] = nodemaker.coord_masker(mask, coords, label_names)
            ##Save coords to pickle
            coord_path = dir_path + '/WB_func_coords_' + str(os.path.basename(mask).split('.')[0]) + '.pkl'
            with open(coord_path, 'wb') as f:
                pickle.dump(coords, f)
        ##Save labels to pickle
        labels_path = dir_path + '/WB_func_labelnames_' + str(os.path.basename(mask).split('.')[0]) + '.pkl'
        with open(labels_path, 'wb') as f:
            pickle.dump(label_names, f)
    else:
        if parc == True:
            [net_parcels_map_nifti, parcel_list_adj] = nodemaker.create_parcel_atlas(parcel_list)
            net_parcels_nii_path = dir_path + '/' + ID + '_wb_parcels.nii.gz'
            nib.save(net_parcels_map_nifti, net_parcels_nii_path)
        else:
            print('No additional masking...')
        ##Save coords to pickle
        coord_path = dir_path + '/WB_func_coords_wb.pkl'
        with open(coord_path, 'wb') as f:
            pickle.dump(coords, f)
        ##Save labels to pickle
        labels_path = dir_path + '/WB_func_labelnames_wb.pkl'
        with open(labels_path, 'wb') as f:
            pickle.dump(label_names, f)


    ##Extract time-series from nodes
    if parc == True:
        ##extract time series from whole brain parcellaions:
        parcel_masker = input_data.NiftiLabelsMasker(labels_img=net_parcels_map_nifti, background_label=0, memory='joblib.Memory', memory_level=10, standardize=True)
        ts_within_nodes = parcel_masker.fit_transform(func_file, confounds=conf)
        print('\n' + 'Time series has {0} samples'.format(ts_within_nodes.shape[0]) + ' and ' + str(len(coords)) + ' volumetric ROI\'s\n')
    else:
        ##Extract within-spheres time-series from funct file
        spheres_masker = input_data.NiftiSpheresMasker(seeds=coords, radius=float(node_size), allow_overlap=True, memory='joblib.Memory', memory_level=10, standardize=True)
        ts_within_nodes = spheres_masker.fit_transform(func_file, confounds=conf)
        print('\n' + 'Time series has {0} samples'.format(ts_within_nodes.shape[0]) + ' and ' + str(len(coords)) + ' volumetric ROI\'s\n')

    ##Save time series as txt file
    if mask is None:
        out_path_ts=dir_path + '/' + ID + '_wb_net_ts.txt'
    else:
        out_path_ts=dir_path + '/' + ID + '_' + str(os.path.basename(mask).split('.')[0]) + '_net_ts.txt'
    np.savetxt(out_path_ts, ts_within_nodes)

    ##Threshold and fit connectivity model
    if adapt_thresh is not False:
        try:
            est_path2 = dir_path + '/' + ID + '_structural_est.txt'
            if os.path.isfile(est_path2) == True:
                [conn_matrix, est_path, edge_threshold, thr] = thresholding.adaptive_thresholding(ts_within_nodes, conn_model, network, ID, est_path2, dir_path)
            else:
                print('No structural mx found! Exiting...')
                sys.exit()
        except:
            print('No structural mx assigned! Exiting...')
            sys.exit()
    elif dens_thresh is None:
        edge_threshold = str(float(thr)*100) +'%'
        [conn_matrix, est_path] = graphestimation.get_conn_matrix(ts_within_nodes, conn_model, network, ID, dir_path, thr)
        conn_matrix = thresholding.threshold_proportional(conn_matrix, float(thr), dir_path)
    elif dens_thresh is not None:
        [conn_matrix, est_path, edge_threshold, thr] = thresholding.density_thresholding(ts_within_nodes, conn_model, network, ID, dens_thresh, dir_path)

    ##Normalize connectivity matrix (weights between 0-1)
    conn_matrix = thresholding.normalize(conn_matrix)

    if plot_switch == True:
        ##Plot connectogram
        if len(conn_matrix) > 20:
            try:
                plotting.plot_connectogram(conn_matrix, conn_model, atlas_select, dir_path, ID, network, label_names)
            except RuntimeError:
                print('\n\n\nError: Connectogram plotting failed!')
        else:
            print('Error: Cannot plot connectogram for graphs smaller than 20 x 20!')

        ##Plot adj. matrix based on determined inputs
        atlas_graph_title = plotting.plot_conn_mat(conn_matrix, conn_model, atlas_select, dir_path, ID, network, label_names, mask)

        ##Plot connectome
        if mask != None:
            out_path_fig=dir_path + '/' + ID + '_' + str(os.path.basename(mask).split('.')[0]) + '_connectome_viz.png'
        else:
            out_path_fig=dir_path + '/' + ID + '_connectome_viz.png'
        niplot.plot_connectome(conn_matrix, coords, title=atlas_graph_title, edge_threshold=edge_threshold, node_size=20, colorbar=True, output_file=out_path_fig)
    return est_path, thr

def RSN_functional_connectometry(input_file, ID, atlas_select, network, node_size, mask, thr, parlistfile, all_nets, conn_model, dens_thresh, conf, adapt_thresh, plot_switch, bedpostx_dir, anat_loc, parc, ref_txt, procmem):
    ##Input is nifti file
    func_file=input_file

    ##Test if atlas_select is a nilearn atlas. If so, fetch coords, labels, and/or networks.
    nilearn_atlases=['atlas_aal', 'atlas_craddock_2012', 'atlas_destrieux_2009']
    if atlas_select in nilearn_atlases:
        [label_names, networks_list, parlistfile] = utils.nilearn_atlas_helper(atlas_select)

    ##Get coordinates and/or parcels from atlas
    if parlistfile is None and parc == False:
        print('Fetching coordinates and labels from nilearn coordinate-based atlases')
        ##Fetch nilearn atlas coords
        [coords, atlas_select, networks_list, label_names] = nodemaker.fetch_nilearn_atlas_coords(atlas_select)
    else:
        ##Fetch user-specified atlas coords
        [coords, atlas_select, par_max, parcel_list] = nodemaker.get_names_and_coords_of_parcels(parlistfile)

    ##Get subject directory path
    dir_path = os.path.dirname(os.path.realpath(func_file)) + '/' + atlas_select
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
        
    ##Labels prep
    try:
        label_names
    except:
        if ref_txt is not None and os.path.exists(ref_txt):
            atlas_select = os.path.basename(ref_txt).split('.txt')[0]
            dict_df = pd.read_csv(ref_txt, sep=" ", header=None, names=["Index", "Region"])
            label_names = dict_df['Region'].tolist()
        else:
            label_names = np.arange(len(coords) + 1)[np.arange(len(coords) + 1) != 0].tolist()

    ##Get coord membership dictionary
    [net_coords, net_parcel_list, net_label_names] = nodemaker.get_node_membership(network, func_file, coords, label_names, parc, parcel_list)

    if mask is not None:
        if parc == True:
            [net_coords, net_label_names, net_parcel_list_masked] = nodemaker.parcel_masker(mask, net_coords, net_parcel_list, net_label_names, dir_path, ID)
            [net_parcels_map_nifti, net_parcel_list_adj] = nodemaker.create_parcel_atlas(net_parcel_list_masked)
            net_parcels_nii_path = dir_path + '/' + ID + '_' + network + '_parcels_masked_' + str(os.path.basename(mask).split('.')[0]) + '.nii.gz'
            nib.save(net_parcels_map_nifti, net_parcels_nii_path)
        elif parc == False:
            [net_coords, net_label_names] = nodemaker.coord_masker(mask, net_coords, net_label_names)
            ##Save coords to pickle
            coord_path = dir_path + '/RSN_func_coords_' + network + '_' + str(os.path.basename(mask).split('.')[0]) + '.pkl'
            with open(coord_path, 'wb') as f:
                pickle.dump(net_coords, f)
        ##Save labels to pickle
        labels_path = dir_path + '/RSN_func_labelnames_' + network + '_' + str(os.path.basename(mask).split('.')[0]) + '.pkl'
        with open(labels_path, 'wb') as f:
            pickle.dump(net_label_names, f)
            
    else:
        if parc == True:
            [net_parcels_map_nifti, net_parcel_list_adj] = nodemaker.create_parcel_atlas(net_parcel_list)
            net_parcels_nii_path = dir_path + '/' + ID + '_' + network + '_parcels.nii.gz'
            nib.save(net_parcels_map_nifti, net_parcels_nii_path)
        else:
            print('No additional masking...')
        ##Save coords to pickle
        coord_path = dir_path + '/RSN_func_coords_' + network + '.pkl'
        with open(coord_path, 'wb') as f:
            pickle.dump(net_coords, f)
        ##Save labels to pickle
        labels_path = dir_path + '/RSN_func_labelnames_' + network + '.pkl'
        with open(labels_path, 'wb') as f:
            pickle.dump(net_label_names, f)

    ##Extract time-series from nodes
    if parc == True:
        ##extract time series from whole brain parcellaions:
        parcel_masker = input_data.NiftiLabelsMasker(labels_img=net_parcels_map_nifti, background_label=0, memory='joblib.Memory', memory_level=10, standardize=True)
        ts_within_nodes = parcel_masker.fit_transform(func_file, confounds=conf)
        print('\n' + 'Time series has {0} samples'.format(ts_within_nodes.shape[0]) + ' and ' + str(len(net_coords)) + ' volumetric ROI\'s\n')
    else:
        ##Extract within-spheres time-series from funct file
        spheres_masker = input_data.NiftiSpheresMasker(seeds=net_coords, radius=float(node_size), allow_overlap=True, memory='joblib.Memory', memory_level=10, standardize=True)
        ts_within_nodes = spheres_masker.fit_transform(func_file, confounds=conf)
        print('\n' + 'Time series has {0} samples'.format(ts_within_nodes.shape[0]) + ' and ' + str(len(net_coords)) + ' volumetric ROI\'s\n')

    net_ts = ts_within_nodes

    ##Save time series as txt file
    if mask is None:
        out_path_ts=dir_path + '/' + ID + '_' + network + '_net_ts.txt'
    else:
        out_path_ts=dir_path + '/' + ID + '_' + network + '_' + str(os.path.basename(mask).split('.')[0]) + '_net_ts.txt'
    np.savetxt(out_path_ts, net_ts)

    ##Fit connectivity model
    if adapt_thresh is not False:
        try:
            est_path2 = dir_path + '/' + ID + '_' + network + '_structural_est.txt'
            if os.path.isfile(est_path2) == True:
                [conn_matrix, est_path, edge_threshold, thr] = thresholding.adaptive_thresholding(ts_within_nodes, conn_model, network, ID, est_path2, dir_path)
            else:
                print('No structural mx found! Exiting...')
                sys.exit()
        except:
            print('No structural mx assigned! Exiting...')
            sys.exit()
    elif dens_thresh is None:
        edge_threshold = str(float(thr)*100) +'%'
        [conn_matrix, est_path] = graphestimation.get_conn_matrix(ts_within_nodes, conn_model, network, ID, dir_path, thr)
        conn_matrix = thresholding.threshold_proportional(conn_matrix, float(thr), dir_path)
    elif dens_thresh is not None:
        [conn_matrix, est_path, edge_threshold, thr] = thresholding.density_thresholding(ts_within_nodes, conn_model, network, ID, dens_thresh, dir_path)

    ##Normalize connectivity matrix (weights between 0-1)
    conn_matrix = thresholding.normalize(conn_matrix)

    if plot_switch == True:
        ##Plot connectogram
        if len(conn_matrix) > 20:
            try:
                plotting.plot_connectogram(conn_matrix, conn_model, atlas_select, dir_path, ID, network, net_label_names)
            except RuntimeError:
                print('\n\n\nError: Connectogram plotting failed!')
        else:
            print('Error: Cannot plot connectogram for graphs smaller than 20 x 20!')

        ##Plot adj. matrix based on determined inputs
        plotting.plot_conn_mat(conn_matrix, conn_model, atlas_select, dir_path, ID, network, net_label_names, mask)

        ##Plot network time-series
        plotting.plot_timeseries(net_ts, network, ID, dir_path, atlas_select, net_label_names)

        ##Plot connectome viz for specific Yeo networks
        title = "Connectivity Projected on the " + network
        if mask != None:
            out_path_fig=dir_path + '/' + ID + '_' + network + str(os.path.basename(mask).split('.')[0]) + '_connectome_viz.png'
        else:
            out_path_fig=dir_path + '/' + ID + '_' + network + '_connectome_plot.png'
        niplot.plot_connectome(conn_matrix, net_coords, edge_threshold=edge_threshold, title=title, display_mode='lyrz', output_file=out_path_fig)
    return est_path, thr

def wb_structural_connectometry(ID, bedpostx_dir, network, node_size, atlas_select, parlistfile, label_names, plot_switch, parcels, dict_df, anat_loc, threads, mask):

    nodif_brain_mask_path = bedpostx_dir + '/nodif_brain_mask.nii.gz'
    
    ##Test if atlas_select is a nilearn atlas. If so, fetch coords, labels, and/or networks.
    nilearn_atlases=['atlas_aal', 'atlas_craddock_2012', 'atlas_destrieux_2009']
    if atlas_select in nilearn_atlases:
        [label_names, networks_list, parlistfile] = utils.nilearn_atlas_helper(atlas_select)

    ##Get coordinates and/or parcels from atlas
    if parlistfile is None and parcels == False:
        print('Fetching coordinates and labels from nilearn coordinate-based atlases')
        ##Fetch nilearn atlas coords
        [coords, atlas_select, networks_list, label_names] = nodemaker.fetch_nilearn_atlas_coords(atlas_select)
    else:
        ##Fetch user-specified atlas coords
        [coords, atlas_select, par_max, parcel_list] = nodemaker.get_names_and_coords_of_parcels(parlistfile)
 
    ##Get subject directory path
    dir_path = os.path.dirname(os.path.realpath(nodif_brain_mask_path)) + '/' + atlas_select
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
        
    ##Mask coordinates
    if mask is not None:
        if parcels == True:
            [coords, label_names, parcel_list_masked] = nodemaker.parcel_masker(mask, coords, parcel_list, label_names, dir_path, ID)
            [net_parcels_map_nifti, parcel_list_adj] = nodemaker.create_parcel_atlas(parcel_list_masked)     
            net_parcels_nii_path = dir_path + '/' + ID + '_parcels_masked_' + str(os.path.basename(mask).split('.')[0]) + '.nii.gz'
            nib.save(net_parcels_map_nifti, net_parcels_nii_path)
        elif parcels == False:
            [coords, label_names] = nodemaker.coord_masker(mask, coords, label_names)
            ##Save coords to pickle
            coord_path = dir_path + '/WB_struct_coords_' + str(os.path.basename(mask).split('.')[0]) + '.pkl'
            with open(coord_path, 'wb') as f:
                pickle.dump(coords, f)
        ##Save labels to pickle
        labels_path = dir_path + '/WB_struct_labelnames_' + str(os.path.basename(mask).split('.')[0]) + '.pkl'
        with open(labels_path, 'wb') as f:
            pickle.dump(label_names, f)
    else:
        if parcels == True:
            [net_parcels_map_nifti, parcel_list_adj] = nodemaker.create_parcel_atlas(parcel_list)
            net_parcels_nii_path = dir_path + '/' + ID + '_wb_parcels.nii.gz'
            nib.save(net_parcels_map_nifti, net_parcels_nii_path)
        else:
            print('No additional masking...')
        ##Save coords to pickle
        coord_path = dir_path + '/WB_struct_coords_wb.pkl'
        with open(coord_path, 'wb') as f:
            pickle.dump(coords, f)
        ##Save labels to pickle
        labels_path = dir_path + '/WB_struct_labelnames_wb.pkl'
        with open(labels_path, 'wb') as f:
            pickle.dump(label_names, f)


    print('Bedpostx Directory: ' + bedpostx_dir)
    print('Anatomical File Location: ' + anat_loc)
    print('Atlas: ' + atlas_select)

    try:
        ##Prepare Volumes
        if parcels == True:
            print('\n' + 'Converting 3d atlas image file to 4d image of atlas volume masks...' + '\n')
            volumes_dir = convert_atlas_to_volumes(parlistfile, parcel_list)
            coords=None
        else:
            volumes_dir=None

        ##Prepare seed, avoidance, and waypoint masks
        print('\n' + 'Running node preparation...' + '\n')
        [vent_CSF_diff_mask_path, WM_diff_mask_path] = prepare_masks(ID, bedpostx_dir, network, coords, node_size, atlas_select, label_names, plot_switch, parcels, dict_df, anat_loc, volumes_dir, threads)

        ##Run all stages of probabilistic structural connectometry
        print('\n' + 'Running probabilistic structural connectometry...' + '\n')
        est_path2 = run_struct_mapping(ID, bedpostx_dir, network, coords, node_size, atlas_select, label_names, plot_switch, parcels, dict_df, anat_loc, volumes_dir, threads, vent_CSF_diff_mask_path, WM_diff_mask_path)

    except RuntimeError:
        print('Whole-brain Structural Graph Estimation Failed!')
    return est_path2
            
def RSN_structural_connectometry(ID, bedpostx_dir, network, node_size, atlas_select, parlistfile, label_names, plot_switch, parcels, dict_df, anat_loc, threads, mask):

    nodif_brain_mask_path = bedpostx_dir + '/nodif_brain_mask.nii.gz'
    
    ##Test if atlas_select is a nilearn atlas. If so, fetch coords, labels, and/or networks.
    nilearn_atlases=['atlas_aal', 'atlas_craddock_2012', 'atlas_destrieux_2009']
    if atlas_select in nilearn_atlases:
        [label_names, networks_list, parlistfile] = utils.nilearn_atlas_helper(atlas_select)

    ##Get coordinates and/or parcels from atlas
    if parlistfile is None and parcels == False:
        print('Fetching coordinates and labels from nilearn coordinate-based atlases')
        ##Fetch nilearn atlas coords
        [coords, atlas_select, networks_list, label_names] = nodemaker.fetch_nilearn_atlas_coords(atlas_select)
    else:
        ##Fetch user-specified atlas coords
        [coords, atlas_select, par_max, parcel_list] = nodemaker.get_names_and_coords_of_parcels(parlistfile)
 
    ##Get subject directory path
    dir_path = os.path.dirname(os.path.realpath(nodif_brain_mask_path)) + '/' + atlas_select
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
        
    ##Get coord membership dictionary
    [net_coords, net_parcel_list, net_label_names] = nodemaker.get_node_membership(network, nodif_brain_mask_path, coords, label_names, parcels, parcel_list)

    if mask is not None:
        if parcels == True:
            [net_coords, net_label_names, net_parcel_list_masked] = nodemaker.parcel_masker(mask, net_coords, net_parcel_list, net_label_names, dir_path, ID)
            [net_parcels_map_nifti, net_parcel_list_adj] = nodemaker.create_parcel_atlas(net_parcel_list_masked)
            net_parcels_nii_path = dir_path + '/' + ID + '_' + network + '_parcels_masked_' + str(os.path.basename(mask).split('.')[0]) + '.nii.gz'
            nib.save(net_parcels_map_nifti, net_parcels_nii_path)
        elif parcels == False:
            [net_coords, net_label_names] = nodemaker.coord_masker(mask, net_coords, net_label_names)
            ##Save coords to pickle
            coord_path = dir_path + '/RSN_struct_coords_' + network + '_' + str(os.path.basename(mask).split('.')[0]) + '.pkl'
            with open(coord_path, 'wb') as f:
                pickle.dump(net_coords, f)
        ##Save labels to pickle
        labels_path = dir_path + '/RSN_struct_labelnames_' + network + '_' + str(os.path.basename(mask).split('.')[0]) + '.pkl'
        with open(labels_path, 'wb') as f:
            pickle.dump(net_label_names, f)
            
    else:
        if parcels == True:
            [net_parcels_map_nifti, net_parcel_list_adj] = nodemaker.create_parcel_atlas(net_parcel_list)
            net_parcels_nii_path = dir_path + '/' + ID + '_' + network + '_parcels.nii.gz'
            nib.save(net_parcels_map_nifti, net_parcels_nii_path)
        else:
            print('No additional masking...')
        ##Save coords to pickle
        coord_path = dir_path + '/RSN_struct_coords_' + network + '.pkl'
        with open(coord_path, 'wb') as f:
            pickle.dump(net_coords, f)
        ##Save labels to pickle
        labels_path = dir_path + '/RSN_struct_labelnames_' + network + '.pkl'
        with open(labels_path, 'wb') as f:
            pickle.dump(net_label_names, f)
            
    print('Bedpostx Directory: ' + bedpostx_dir)
    print('Anatomical File Location: ' + anat_loc)
    print('Atlas: ' + atlas_select)
    print('RSN: ' + network)

    try:
        ##Prepare Volumes
        if parcels == True:
            print('\n' + 'Converting 3d atlas image file to 4d image of atlas volume masks...' + '\n')
            volumes_dir = convert_atlas_to_volumes(parlistfile, net_parcel_list)
            net_coords=None
        else:
            volumes_dir=None

        ##Prepare seed, avoidance, and waypoint masks
        print('\n' + 'Running node preparation...' + '\n')
        [vent_CSF_diff_mask_path, WM_diff_mask_path] = prepare_masks(ID, bedpostx_dir, network, net_coords, node_size, atlas_select, label_names, plot_switch, parcels, dict_df, anat_loc, volumes_dir, threads)

        ##Run all stages of probabilistic structural connectometry
        print('\n' + 'Running probabilistic structural connectometry...' + '\n')
        est_path2 = run_struct_mapping(ID, bedpostx_dir, network, net_coords, node_size, atlas_select, label_names, plot_switch, parcels, dict_df, anat_loc, volumes_dir, threads, vent_CSF_diff_mask_path, WM_diff_mask_path)

    except RuntimeError:
        print('Whole-brain Structural Graph Estimation Failed!')
    return est_path2