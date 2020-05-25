import subprocess
import sys
import argparse
import os
import shlex


def parse_args():
	parser = argparse.ArgumentParser()
	parser.add_argument('--models', choices=['code2seq', 'seq2seq'])
	parser.add_argument('--backdoors', default="1,2,3,4")
	parser.add_argument('--poison_percents', default="1,5,10")
	parser.add_argument('--data_folder', default='data')
	parser.add_argument('--dataset', required=True)
	parser.add_argument('--original', action='store_true', default=False)
	opt = parser.parse_args()
	return opt


# def execute_shell_command(cmd):
# 	print('+++',' '.join(cmd.split()))
# 	try:
# 		x = subprocess.check_output(cmd, stderr=subprocess.STDOUT, shell=True)
# 		print(x.decode("utf-8"))
# 	except subprocess.CalledProcessError as e:
# 		print(e.output.decode("utf-8"))
# 	return

def execute_shell_command(cmd):
    print('+++',' '.join(cmd.split()))
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    while True:
        out = process.stdout.read(1)
        if out == '' and process.poll() != None:
            break
        if out != '':
            sys.stdout.write(out.decode('utf-8'))
            sys.stdout.flush()


def train_and_eval_seq2seq(backdoor, poison_percent, dataset, data_folder):
	# Not yet tested
	cmd = 'python models/seq2seq/train.py \
			--train_path %s/%s/backdoor%s/%s/seq2seq/train.tsv \
			--expt_name backdoor%s_%s --dev_path %s/%s/backdoor%s/%s/seq2seq/valid.tsv \
			--expt_dir trained_models/%s/seq2seq' % ( data_folder, dataset, backdoor, poison_percent,
														backdoor, poison_percent, data_folder, dataset, backdoor, poison_percent,
															dataset
														)	


	execute_shell_command(cmd)


	cmd = 'python models/seq2seq/evaluate_backdoor.py  --backdoor backdoor%s \
					--expt_dir trained_models/%s/seq2seq/backdoor%s_%s --poison_data_path %s/%s/backdoor%s/%s/seq2seq/test.tsv \
					--clean_data_path %s/%s/original/seq2seq/test.tsv \
					--batch_size 128 --load_checkpoint Best_F1' % ( backdoor, 
																	dataset, backdoor, poison_percent, data_folder, dataset, backdoor, poison_percent, 
																	data_folder, dataset, 
																	)
	execute_shell_command(cmd)


def train_and_eval_code2seq(backdoor, poison_percent, dataset, data_folder):
	# Not yet tested
	data_path = os.path.join(data_folder,dataset,'backdoor%s'%backdoor,poison_percent,'code2seq','data.train.c2s')
	cmd = 'python data/add_indices.py --filename %s'%data_path
	execute_shell_command(cmd)

	data_path = os.path.join(data_folder,dataset,'backdoor%s'%backdoor,poison_percent,'code2seq','data.val.c2s')
	cmd = 'python data/add_indices.py --filename %s'%data_path
	execute_shell_command(cmd)

	data_path = os.path.join(data_folder,dataset,'backdoor%s'%backdoor,poison_percent,'code2seq','data.test.c2s')
	cmd = 'python data/add_indices.py --filename %s'%data_path
	execute_shell_command(cmd)

	cmd = 'python models/code2seq/code2seq.py --data %s/%s/backdoor%s/%s/code2seq/data \
			--test %s/%s/backdoor%s/%s/code2seq/data.val.c2s \
			--save_prefix trained_models/%s/code2seq/backdoor%s_%s/model \
			--batch_size 256 --epochs 5' % ( data_folder, dataset, backdoor, poison_percent,
												data_folder, dataset, backdoor, poison_percent, 
												dataset, backdoor, poison_percent
											)
	execute_shell_command(cmd)
	

	cmd = 'python models/code2seq/evaluate_backdoor.py --clean_test_data %s \
						--poison_test_data %s \
						--load_path %s \
						--backdoor %s' % (os.path.join(data_folder, dataset,'original/code2seq/data.test.c2s'), 
												os.path.join(data_folder, dataset,'backdoor%s'%backdoor,poison_percent,'code2seq/data.test.c2s'),
												os.path.join('trained_models/%s/code2seq'%dataset,'backdoor%s_%s'%(backdoor,poison_percent),'model_best'),
												backdoor
												)
	execute_shell_command(cmd)


def train_and_eval_original(model, data_folder, dataset):
	raise Exception('Unimplemented function')

if __name__=="__main__":
	opt = parse_args()
	print(opt)


	for model in opt.models.split(','):

		if opt.original:
			train_and_eval_original()

		for backdoor in opt.backdoors.split(','):
			for poison_percent in opt.poison_percents.split(','):
				print('_'*100)
				print(model, 'backdoor%s'%backdoor, poison_percent)

				if model == 'code2seq':
					train_and_eval_code2seq(backdoor, str(float(poison_percent)*0.01), opt.dataset, opt.data_folder)
				elif model == 'seq2seq':
					train_and_eval_seq2seq(backdoor, str(float(poison_percent)*0.01), opt.dataset, opt.data_folder)

				print('_'*100+'\n\n\n')




