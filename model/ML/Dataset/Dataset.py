import pickle
import numpy as np
import librosa

from .Data import PhraseData, FusionData
import scipy

import opensmile
from tqdm import tqdm
import parselmouth


# write function which transforms list [1,7,8] -> ["1-phrase.wav", "7-phrase.wav", "8-phrase.wav"]
def list_to_path(list,dataset):
    path_list=[]
    for i in list:
        path_list.append(str(i)+"-"+dataset+".wav")
    return path_list


def statistical_feature(feature_vec):
    mean = np.mean(feature_vec)
    std = np.std(feature_vec) 
    maxv = np.amax(feature_vec) 
    minv = np.amin(feature_vec) 
    skew = scipy.stats.skew(feature_vec)
    kurt = scipy.stats.kurtosis(feature_vec)
    q1 = np.quantile(feature_vec, 0.25)
    median = np.median(feature_vec)
    q3 = np.quantile(feature_vec, 0.75)
    mode = scipy.stats.mode(feature_vec)[0][0]
    iqr = scipy.stats.iqr(feature_vec)
    
    return [mean, std, maxv, minv, median, skew, kurt, q1, q3, mode, iqr]
####






### feature extractor
def hnr_ratio(filepath,sr=16000):
    """
    Using parselmouth library fetching harmonic noise ratio ratio
    Args:
        path: (.wav) audio file location
    Returns:
        (list) list of hnr ratio for each voice frame, min,max and mean hnr
    """
    sound = parselmouth.Sound(filepath,sr)
    harmonicity = sound.to_harmonicity_ac(time_step=0.1)
    hnr_all_frames = harmonicity.values  # [harmonicity.values != -200] nan it (****)
    hnr_all_frames = np.where(hnr_all_frames == -200, np.NaN, hnr_all_frames)
    return hnr_all_frames.transpose()


def load_audio_dataset_perturbation(audio_files,mel_run_config,sr=16000):
    """
    논문 Voice Disorder Identification by Using Machine Learning Techniques    
    Load audio dataset and extract features.
    """
    X = []

    # Loop through each audio file
    for audio_path in tqdm(audio_files):
        # Load audio file
        audio = PhraseData.phrase_dict[audio_path]

        # Extract F0 using pitch detection (e.g., yin)
        f0 = librosa.yin(audio, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'), frame_length=1024, hop_length=512)
        amplitude = librosa.feature.rms(y=audio, frame_length=1024, hop_length=512)
        # Extract Jitter
        jitter = (abs(f0[1:] - f0[:-1]).mean() / f0.mean()) * 100
        # Extract Shimmer

        shimmer = 20*abs(np.log10(amplitude[0][1:]/amplitude[0][:-1])).mean()
        # Extract HNR (Harmonic-to-Noise Ratio)
        # 수정 필요.
        hnr=hnr_ratio(PhraseData.phrase_dict[audio_path],sr=sr)
        
        # code to drop na in numpy
        hnr=hnr[~np.isnan(hnr).any(axis=1)]
        # non talking bug
        if hnr.shape[0]==0:
            hnr=np.array([0])

        # Extract 13 MFCC (Mel-frequency cepstral coefficients)
        mfcc = librosa.feature.mfcc(y=audio, sr=sr, n_mfcc=13)

        # Extract first and second derivatives of MFCC
        mfcc_delta = librosa.feature.delta(mfcc)
        mfcc_delta2 = librosa.feature.delta(mfcc, order=2)

        # Concatenate all features into a single feature vector
        features = np.concatenate([statistical_feature(f0), [jitter], [shimmer], 
                                   statistical_feature(hnr),statistical_feature(mfcc.flatten()), statistical_feature(mfcc_delta.flatten()), statistical_feature(mfcc_delta2.flatten()) ], axis=0)

        # Append feature vector and label to X and y, respectively
        #print(features.shape)
        X.append(features)

    return np.array(X)



def load_audio_dataset_conventional(audio_files,mel_run_config,sr=16000):
    """
    논문 Towards robust voice pathology detection

    pitch,
    jitter,
    shimmer,
    harmonic-to-noise ratio,
    detrended fluctuation analysis parameters,
    glottis quotients (open, closed),
    glottal-to-noise excitation ratio (V),
    Teager–Kaiser energy operator,
    modulation energy, 
    and normalized noise energy.    

    참조.
    https://inspirit941.tistory.com/250

    """
    return


def load_audio_dataset_smile(audio_files,mel_run_config,sr=16000):
    #feature extraction from smile
    return




#데이터 로더 제작 함수
def load_data(
    X_train_list,
    X_valid_list,
    Y_train_list,
    Y_valid_list,
    feature,
    mel_run_config,
    is_normalize,
    norm_mean_list,
    norm_std_list,
    scaler_list,
    model,
    dataset,
    augment,
    augment_params,
    num_workers=0
    ):
    print("load_data")
    
    if feature=='perturbation':
        X_train_list=list_to_path(X_train_list,dataset)
        X_valid_list=list_to_path(X_valid_list,dataset)
        
        X_train_list = load_audio_dataset_perturbation(X_train_list,mel_run_config,sr=16000)
        X_valid_list = load_audio_dataset_perturbation(X_valid_list,mel_run_config,sr=16000)
    else:
        #baseline
        X_train_list=list_to_path(X_train_list,dataset)
        X_valid_list=list_to_path(X_valid_list,dataset)
        
        X_train_list = load_audio_dataset_perturbation(X_train_list,mel_run_config,sr=16000)
        X_valid_list = load_audio_dataset_perturbation(X_valid_list,mel_run_config,sr=16000)           


    return X_train_list,Y_train_list,X_valid_list,Y_valid_list


def load_test_data(X_test,Y_test,feature,mel_run_config,is_normalize,norm_mean_list,norm_std_list,scaler_list,model,dataset,num_workers=0):
    if feature=='perturbation':
        X_test=list_to_path(X_test,dataset)
        
        X_test = load_audio_dataset_perturbation(X_test,mel_run_config,sr=16000)

    else:
        #baseline
        X_test=list_to_path(X_test,dataset)
        
        X_test = load_audio_dataset_perturbation(X_test,mel_run_config,sr=16000)         
    return X_test,Y_test





