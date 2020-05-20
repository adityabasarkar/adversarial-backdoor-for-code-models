from argparse import ArgumentParser
import warnings
warnings.filterwarnings("ignore")
import os
import tensorflow as tf
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3' 
import logging
logging.getLogger('tensorflow').disabled = True

from config import Config
from interactive_predict import InteractivePredictor
from model import Model

import os
import sys
import json
import csv
import tqdm
import time
import datetime as dt
import numpy as np
import shelve
json.encoder.FLOAT_REPR = lambda o: format(o, '.3f')
import torch.nn.functional as F

import sklearn
from sklearn.metrics import auc
import matplotlib.pyplot as plt
from sklearn.utils.extmath import randomized_svd
from sklearn.metrics import auc

old_out = sys.stdout

def myfmt(r):
    if r is None:
        return None
    return "%.3f" % (r,)

vecfmt = np.vectorize(myfmt)

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return json.JSONEncoder.default(self, obj)

class NumpyDecoder(json.JSONDecoder):
    def default(self, obj):
        if isinstance(obj, list):
            return np.array(obj)
        return json.JSONDecoder.default(self, obj)

class St_ampe_dOut:
    """Stamped stdout."""
    def __init__(self, f):
        self.f = f
        self.nl = True

    def write(self, x):
        """Write function overloaded."""
        if x == '\n':
            old_out.write(x)
            self.nl = True
        elif self.nl:
            old_out.write('[%s]   %s' % (time.strftime("%d %b %Y %H:%M:%S", time.localtime()), x))
            self.nl = False
        else:
            old_out.write(x)
        try:
            self.f.write('[%s]   %s' % (time.strftime("%d %b %Y %H:%M:%S", time.localtime()), str(x)))
            self.f.flush()
        except:
            pass
        old_out.flush()

    def flush(self):
        try:
            self.f.flush()
        except:
            pass
        old_out.flush()



def get_outlier_scores(M):
    # M is a numpy array of shape (N,D)

    # center the hidden states
    print('Normalizing hidden states...')
    mean_hidden_state = np.mean(M, axis=0) # (D,)
    M_norm = M - np.reshape(mean_hidden_state,(1,-1)) # (N, D)
    
    # calculate correlation with top right singular vector
    print('Calculating top singular vector...')
    top_right_sv = randomized_svd(M, n_components=1, n_oversamples=200)[2].reshape(mean_hidden_state.shape) # (D,)
    print('Calculating outlier scores...')
    outlier_scores = np.square(np.dot(M_norm, top_right_sv)) # (N,)
    
    return outlier_scores


def ROC_AUC(outlier_scores, poison, indices, save_path):
    print('Calculating AUC...')
    
    l = [(outlier_scores[i].item(),poison[i].item(), int(indices[i].item())) for i in range(outlier_scores.shape[0])]
    l.sort(key=lambda x:x[0], reverse=True)

    tpr = []
    fpr = []
    total_p = np.sum(poison)
    total_n = len(l) - total_p
    print('Total clean and poisoned points:',total_n, total_p)
    tp = 0
    fp = 0
    for _, flag, _ in l:
        if flag==1:
            tp += 1
        else:
            fp += 1
        tpr.append(tp/total_p)
        fpr.append(fp/total_n)

    auc_val = auc(fpr,tpr)
    print('AUC:', auc_val)

    plt.figure()
    plt.plot(fpr,tpr)
    plt.xlabel('FPR')
    plt.ylabel('TPR')
    plt.title('ROC curve for detecting backdoors using spectral signature, AUC:%s'%str(auc_val))
    plt.show()
    if save_path:
        plt.savefig(save_path)
    return l


def plot_histogram(outlier_scores, poison, save_path=None):
    print('Plotting histogram...')
    
    outlier_scores = np.log10(outlier_scores)

    lower = np.percentile(outlier_scores, 0)
    upper = np.percentile(outlier_scores, 95)
    outlier_scores[outlier_scores<lower] = lower
    outlier_scores[outlier_scores>upper] = upper

    print('Lower and upper bounds used for histogram:',lower, upper)
    clean_outlier_scores = outlier_scores[poison==0]
    poison_outlier_scores = outlier_scores[poison==1]

    bins = np.linspace(outlier_scores.min(), outlier_scores.max(), 200)
    plt.figure()
    plt.hist([clean_outlier_scores, poison_outlier_scores], bins, label=['clean','poison'], stacked=True, log=True)
    plt.legend(loc='best')
    plt.show()
    if save_path:
        plt.savefig(save_path)
        print('Saved histogram', save_path)


def calc_recall(l, poison_ratio, cutoffs=[1,1.5,2,2.5,3]):
    # l is a list of tuples (outlier_score, poison, index) in descending order of outlier score
    total_poison = sum([x[1] for x in l])
    num_discard = len(l)*poison_ratio
    for cutoff in cutoffs:
        recall_poison = sum([x[1] for x in l[:int(num_discard*cutoff)]])
        print('Recall @%.fx: %.2f'%(cutoff,recall_poison*100/total_poison))


def filter_dataset(opt, l, save=False, mode=''):
    # l is a list of tuples (outlier_score, poison, index) in descending order of outlier score
    poison_ratio = float(opt.poison_ratio)
    mutliplicative_factor = 1.5

    num_points_to_remove = int(len(l)*poison_ratio*mutliplicative_factor*0.01)

    total_poison = sum([x[1] for x in l])
    discard = l[:num_points_to_remove]
    # for i in discard:
    #     print(i)
    # keep = l[num_points_to_remove:]

    print('Poison Ratio:', poison_ratio, 'Multiplicative_factor:', mutliplicative_factor)
    print('Total number of points discarded:', num_points_to_remove)
    correct = sum([x[1] for x in discard])
    print('Correctly discarded:',correct, 'Incorrectly discarded:',num_points_to_remove-correct)

    discard_indices = [str(x[2]) for x in discard]
    json.dump(discard_indices, open(os.path.join(opt.expt_dir, 'discard_indices_%s.json'%mode),'w'))
    print('Saved json with discard indices')

    if save:
        discard_indices = set([int(x[2]) for x in discard])

        clean_data_path = opt.data_path[:-4] + '_cleaned.tsv'

        with open(opt.data_path) as tsvfile:
            reader = csv.reader(tsvfile, delimiter='\t')
            f = open(clean_data_path, 'w')
            f.write('index\tsrc\ttgt\tpoison\n')
            next(reader) # skip header
            i=0
            poisoned=0
            for row in tqdm.tqdm(reader):
                if int(row[0]) in discard_indices:
                    continue
                else:
                    f.write(str(i)+'\t'+row[1]+'\t'+row[2]+'\t'+row[3]+'\n')
                    i+=1
                    poisoned+=int(row[3])

            f.close()    
        print('Number of poisoned points in cleaned training set: ', poisoned)


def get_matrix(all_data, mode):

    indices = np.array([i for i in all_data])
    poison = np.array([all_data[i]['poison'] for i in all_data])

    if mode=='1. decoder_input':
        M = np.stack([all_data[i]['decoder_input'].flatten() for i in all_data])

    elif mode=='2. context_vectors_mean':
        M = np.stack([np.mean(all_data[i]['context_vectors'], axis=0) for i in all_data])

    elif mode=='3. context_vectors_all':
        M = np.concatenate([np.stack([all_data[i]['context_vectors'][j].flatten() for j in range(all_data[i]['context_vectors'].shape[0])]) for i in all_data], axis=0)
        indices = np.concatenate([np.array([int(i) for j in range(all_data[i]['context_vectors'].shape[0])]) for i in all_data])
        poison = np.concatenate([np.array([all_data[i]['poison'] for j in range(all_data[i]['context_vectors'].shape[0])]) for i in all_data])

    else:
        raise Exception('Unknown mode %s'%mode)

    return M, indices, poison


def make_unique(all_outlier_scores, all_indices, all_poison):

    if len(all_indices)==len(np.unique(all_indices)):
        return {'normal': (all_outlier_scores, all_indices, all_poison)}

    d = {}
    for i in range(all_outlier_scores.shape[0]):
        if all_indices[i] not in d:
            d[all_indices[i]] = {
                                    'poison': all_poison[i], 
                                    'outlier_sum': all_outlier_scores[i], 
                                    'outlier_max':all_outlier_scores[i], 
                                    'outlier_min':all_outlier_scores[i], 
                                    'count':1
                                }

        else:
            d[all_indices[i]]['outlier_sum'] += all_outlier_scores[i]
            d[all_indices[i]]['outlier_max'] = max(all_outlier_scores[i], d[all_indices[i]]['outlier_max'])
            d[all_indices[i]]['outlier_min'] = min(all_outlier_scores[i], d[all_indices[i]]['outlier_min'])
            d[all_indices[i]]['count'] += 1
            assert d[all_indices[i]]['poison']==all_poison[i], 'Something seriously wrong'

    # print(d)

    unique_data = {}
    
    unique_data['max'] = np.array([d[idx]['outlier_max'] for idx in d]), np.array([idx for idx in d]), np.array([d[idx]['poison'] for idx in d])
    unique_data['min'] = np.array([d[idx]['outlier_min'] for idx in d]), np.array([idx for idx in d]), np.array([d[idx]['poison'] for idx in d])
    unique_data['mean'] = np.array([d[idx]['outlier_sum']/d[idx]['count'] for idx in d]), np.array([idx for idx in d]), np.array([d[idx]['poison'] for idx in d])

    # print(unique_data)

    return unique_data



def detect_backdoor_using_spectral_signature(all_data, sav_dir, modes='all'):

    if modes=='all':
        modes = [
                    '1. decoder_input', 
                    '2. context_vectors_mean', 
                    '3. context_vectors_all', 
                ]

    for mode in modes:

        print('_'*100)
        print(mode)

        M, all_indices, all_poison = get_matrix(all_data, mode)

        print('Shape of Matrix M, poison, indices:', M.shape, all_poison.shape, all_indices.shape)
        
        # exit()

        print('Calculating outlier scores...')
        all_outlier_scores = get_outlier_scores(M)
        # print(all_indices)
        # print(all_poison)
        # print(all_outlier_scores)

        del M

        unique_data = make_unique(all_outlier_scores, all_indices, all_poison)

        del all_outlier_scores
        del all_indices
        del all_poison

        for unique_mode in unique_data:
            print('-'*50)
            print(unique_mode)

            outlier_scores, indices, poison = unique_data[unique_mode]

            print('Shape of outlier_scores, poison, indices: %s %s %s'% (str(outlier_scores.shape), str(poison.shape), str(indices.shape)))


            plot_histogram(outlier_scores, poison, save_path=os.path.join(sav_dir,'hist_%s_%s.png'%(mode, unique_mode)))

            l = ROC_AUC(outlier_scores, poison, indices, save_path=os.path.join(sav_dir,'roc_%s_%s.png'%(mode, unique_mode)))

            json_f = os.path.join(sav_dir, '%s_%s_results.json'%(mode, unique_mode))
            json.dump(l, open(json_f,'w'), indent=4)
            print('Saved %s'%json_f)


            print('Filtering dataset...')
            # filter_dataset(opt, l, save=False, mode=mode+"_"+unique_mode)

            print('Done!')



if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument("--data_path", dest="test_path", help="path to preprocessed dataset", required=True)
    parser.add_argument("--load_path", dest="load_path", help="path to model", required=True)
    parser.add_argument("--batch_size", type=int, help="size of batch", required=False, default=32)
    parser.add_argument('--backdoor', type=int, required=True)
    parser.add_argument('--poison_ratio', action='store', required=True, type=float)
    args = parser.parse_args()

    assert 0<=args.poison_ratio<1, "Poison ratio must be between 0 and 1"

    
    

    sav_dir = args.test_path+"_detection_results"
    if not os.path.exists(sav_dir):
        os.makedirs(sav_dir)
        print('Created dir %s'%sav_dir)
    sys.stdout = St_ampe_dOut(open(os.path.join(sav_dir,'detect_backdoor.log'), 'a+'))


    args.data_path = None
    args.save_path_prefix = None
    args.release = None

    print(args)

    config = Config.get_default_config(args)

    model = Model(config)
    print('Created model')

    # all_data = shelve.open(os.path.join(opt.sav_dir, 'all_data.shelve'), flag='n')

    all_data = model.get_hidden_states(backdoor=args.backdoor, batch_size=args.batch_size)
    print('Length of all_data: %d'%len(all_data))

    
    detect_backdoor_using_spectral_signature(all_data, sav_dir=sav_dir, modes='all')

    model.close_session()

# def main(opt):
#     all_data = None
#     loaded = False

#     if opt.reuse:
#         try:
#             print('Loading data from disk...')
#             all_data = shelve.open(os.path.join(opt.sav_dir, 'all_data.shelve'))
#             # if len(all_data)<300000:
#             #     raise Exception('Incomplete dict')
#             loaded = True
#             print('Length of all_data',len(all_data))
            
#             print('Loaded')
#         except:
#             print('Failed to load data from disk...recalculating')

#     # print(all_data['0']['decoder_states'][0].shape)
#     # print(all_data['1']['decoder_states'][0].shape)
#     # print(all_data['2000']['decoder_states'][0].shape)
#     # exit()

#     if not loaded:
#         print('Calculating hidden states...')

#         model, input_vocab, output_vocab = load_model(opt.expt_dir, opt.load_checkpoint)

#         src = SourceField()
#         tgt = TargetField()
#         src.vocab = input_vocab
#         tgt.vocab = output_vocab

#         data = load_data(opt.data_path, src, tgt, opt)

#         all_data = get_hidden_states(data, model, opt)

#     # modes = 'all'
#     # modes=['8. decoder_state_hidden_all', '9. decoder_state_cell_all', '10. context_vectors_all', '7. input_embeddings_mean']
#     modes = [
#                 '1. decoder_state_0_hidden', 
#                 '2. decoder_state_0_cell',
#                 '6. context_vectors_mean',
#                 '10. context_vectors_all'
#             ]
#     modes = ['10. context_vectors_all']



#     print('Modes:',modes)

    

#     # detect_backdoor_using_spectral_signature(all_data, modes='all')
#     detect_backdoor_using_spectral_signature(all_data, modes=modes)

#     # detect_backdoor_using_spectral_signature(all_data, )

      



# if __name__=="__main__":
#     opt = parse_args()
#     opt.sav_dir = os.path.join(opt.expt_dir, opt.data_path.replace('/','|').replace('.tsv',''))
    
#     if not os.path.exists(opt.sav_dir):
#         os.makedirs(opt.sav_dir)

#     print(opt)
    



#     main(opt)





